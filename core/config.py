"""
配置管理模块

兼容 C++ Theresa-0328/MHY_Scanner 的 userinfo.json 格式，两种格式互通：
  - C++ 格式: account[n].{access_key, uid, name, type, note, mid}
  - Python 格式: accounts[n].{token, uid, name, server_type, game_type, notes, mid}

通过 MHY_USERINFO_PATH 环境变量可指向外部 C++ 项目的配置文件。
"""
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, asdict, field
from .logger import config_log, error


def get_base_dir() -> Path:
    """获取程序基准目录（兼容打包后的路径）"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def get_accounts_file_path() -> Path:
    """
    获取账号配置文件路径（userinfo.json，与 C++ 项目兼容）：
    1. 优先使用 MHY_USERINFO_PATH 环境变量
    2. 其次使用 ./Config/userinfo.json
    """
    env_path = os.environ.get("MHY_USERINFO_PATH", "")
    if env_path:
        p = Path(env_path)
        if p.is_absolute():
            return p
        return get_base_dir() / p
    return get_base_dir() / "Config" / "userinfo.json"


def get_settings_file_path() -> Path:
    """获取应用设置配置文件路径：./Config/config.json"""
    return get_base_dir() / "Config" / "config.json"


# ---- 类型映射：C++ type 字符串 <-> (server_type, game_type) ----
# C++ type 字段只有两个值:
#   "官服"     -> server_type=1, game_type=4 (默认原神)
#   "崩坏3B服"  -> server_type=2, game_type=1 (崩坏3)
# Python 内部还支持 game_type 细分，以下双向映射：

_TYPE_MAP_TO_CPP = {
    (1, 1): "崩坏3B服",          # BiliBili, Honkai3
    (2, 1): "崩坏3B服",          # BiliBili, Honkai3 (同)
    (1, 4): "官服",              # Official, Genshin
    (1, 8): "官服",              # Official, HonkaiStarRail
    (1, 12): "官服",             # Official, ZenlessZoneZero
    (1, 1): "官服",              # Official, Honkai3
}

_TYPE_MAP_FROM_CPP = {
    "官服": (1, 4),              # 默认: 官服+原神
    "崩坏3B服": (2, 1),           # B服+崩坏3
}


@dataclass
class Account:
    """账号信息（内部统一格式）"""
    uid: str
    name: str
    token: str      # access_key / stoken
    mid: str = ""
    server_type: int = 1  # 1=官服, 2=BiliBili
    game_type: int = 4   # 4=原神, 1=崩坏3, 8=星穹铁道, 12=绝区零
    notes: str = ""
    last_login: str = ""
    last_room_id: str = ""

    # ---- C++ 格式互转 ----

    @staticmethod
    def from_cpp_dict(d: dict) -> "Account":
        """从 C++ 格式 dict 创建 Account"""
        cpp_type = d.get("type", "官服")
        server_type, game_type = _TYPE_MAP_FROM_CPP.get(cpp_type, (1, 4))
        return Account(
            uid=str(d.get("uid", "")),
            name=d.get("name", ""),
            token=d.get("access_key", ""),
            mid=d.get("mid", ""),
            server_type=server_type,
            game_type=game_type,
            notes=d.get("note", ""),
        )

    def to_cpp_dict(self) -> dict:
        """转换为 C++ 格式 dict"""
        cpp_type = _TYPE_MAP_TO_CPP.get(
            (self.server_type, self.game_type),
            "官服" if self.server_type == 1 else "崩坏3B服"
        )
        return {
            "access_key": self.token,
            "uid": self.uid,
            "name": self.name,
            "type": cpp_type,
            "note": self.notes,
            "mid": self.mid,
        }


@dataclass
class AppConfig:
    """应用配置"""
    auto_exit: bool = False
    auto_login: bool = True
    auto_start: bool = False
    last_platform: int = 0  # 0=抖音, 1=BiliBili
    last_room_id_douyin: str = ""
    last_room_id_bilibili: str = ""
    default_account_uid: str = ""
    default_account_server_type: int = 1
    log_output_mode: str = "console" if not getattr(sys, 'frozen', False) else "file"  # "console" / "file"
    log_level: int = 0 if not getattr(sys, 'frozen', False) else 2  # 0=DEBUG, 1=INFO, 2=WARN, 3=ERROR
    editor_font: dict = field(default_factory=lambda: {
        "english_family": "Consolas",
        "chinese_family": "Microsoft YaHei",
        "size": 11,
        "bold": False,
        "italic": False,
    })
    accounts: List[Account] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> 'AppConfig':
        """从 dict 加载（自动识别 C++ / Python 格式）"""
        accounts = []
        is_cpp_format = False

        # 1. 检测格式：C++ 用 "account"（单数），Python 用 "accounts"（复数）
        if "account" in data:
            raw_accounts = data["account"]
            is_cpp_format = True
        else:
            raw_accounts = data.get("accounts", data.get("account", []))

        # 2. 解析账号
        for acc in raw_accounts:
            if isinstance(acc, Account):
                accounts.append(acc)
            elif isinstance(acc, dict):
                if is_cpp_format or "access_key" in acc:
                    # C++ 格式
                    accounts.append(Account.from_cpp_dict(acc))
                else:
                    # Python 格式
                    try:
                        accounts.append(Account(**acc))
                    except Exception:
                        accounts.append(Account.from_cpp_dict(acc))

        # 3. 解析默认账号
        default_uid = data.get("default_account_uid", "")
        default_server = data.get("default_account_server_type", 1)

        # C++ 格式的 last_account 是 1-based 索引
        if not default_uid and "last_account" in data:
            idx = int(data["last_account"])
            if isinstance(idx, int) and 1 <= idx <= len(accounts):
                acc = accounts[idx - 1]
                default_uid = acc.uid
                default_server = acc.server_type

        # 兼容旧版 room_id 迁移
        last_room_douyin = data.get("last_room_id_douyin", data.get("last_room_id", ""))
        last_room_bili = data.get("last_room_id_bilibili", "")

        # 编辑器字体
        default_font = {
            "english_family": "Consolas",
            "chinese_family": "Microsoft YaHei",
            "size": 11,
            "bold": False,
            "italic": False,
        }
        editor_font = data.get("editor_font", default_font)
        if not isinstance(editor_font, dict):
            editor_font = default_font

        return cls(
            auto_exit=data.get("auto_exit", False),
            auto_login=data.get("auto_login", True),
            auto_start=data.get("auto_start", False),
            last_platform=data.get("last_platform", 0),
            last_room_id_douyin=last_room_douyin,
            last_room_id_bilibili=last_room_bili,
            default_account_uid=default_uid,
            default_account_server_type=default_server,
            log_output_mode=data.get("log_output_mode", "console" if not getattr(sys, 'frozen', False) else "file"),
            log_level=data.get("log_level", 0 if not getattr(sys, 'frozen', False) else 2),
            editor_font=editor_font,
            accounts=accounts,
        )

    def to_accounts_dict(self) -> dict:
        """
        导出账号数据，写入 userinfo.json（C++ 兼容格式）。
        仅包含账号列表和默认账号索引，不含应用设置。
        """
        result = {
            "last_account": 0,
            "num": len(self.accounts),
            "account": [acc.to_cpp_dict() for acc in self.accounts],
            "default_account_uid": self.default_account_uid,
            "default_account_server_type": self.default_account_server_type,
        }

        # 解析 last_account（1-based 索引）
        if self.default_account_uid:
            for i, acc in enumerate(self.accounts):
                if (acc.uid == self.default_account_uid and
                        acc.server_type == self.default_account_server_type):
                    result["last_account"] = i + 1
                    break

        return result

    def to_settings_dict(self) -> dict:
        """
        导出应用设置，写入 config.json。
        不含账号列表。
        """
        return {
            "auto_exit": self.auto_exit,
            "auto_login": self.auto_login,
            "auto_start": self.auto_start,
            "last_platform": self.last_platform,
            "last_room_id_douyin": self.last_room_id_douyin,
            "last_room_id_bilibili": self.last_room_id_bilibili,
            "log_output_mode": self.log_output_mode,
            "log_level": self.log_level,
            "editor_font": self.editor_font,
        }

    def get_last_room_id(self, platform: int) -> str:
        """获取指定平台的最后直播间ID"""
        return self.last_room_id_douyin if platform == 0 else self.last_room_id_bilibili

    def set_last_room_id(self, platform: int, room_id: str):
        """设置指定平台的最后直播间ID"""
        if platform == 0:
            self.last_room_id_douyin = room_id
        else:
            self.last_room_id_bilibili = room_id


class ConfigManager:
    """配置管理器（单例）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._accounts_file = get_accounts_file_path()
        self._settings_file = get_settings_file_path()
        self._config: AppConfig = self._load_config()
        config_log(f"账号配置文件: {self._accounts_file}")
        config_log(f"设置配置文件: {self._settings_file}")

        # 首次运行时自动创建 Config 目录和 config.json（默认值）
        if not self._settings_file.exists():
            self.save_settings()
            config_log(f"已自动创建默认设置文件: {self._settings_file}")

    def _load_config(self) -> AppConfig:
        """加载配置：settings 从 config.json 读取（兼容旧版从 userinfo.json 回退），
        accounts 始终从 userinfo.json 读取。"""
        settings_data: dict = {}
        accounts_data: dict = {}

        # 1. 加载应用设置（优先 config.json）
        if self._settings_file.exists():
            try:
                with open(self._settings_file, 'r', encoding='utf-8') as f:
                    settings_data = json.load(f)
            except Exception as e:
                error(f"加载设置文件失败: {e}\n{traceback.format_exc()}")

        # 2. 加载账号数据（始终从 userinfo.json）
        if self._accounts_file.exists():
            try:
                with open(self._accounts_file, 'r', encoding='utf-8') as f:
                    accounts_data = json.load(f)
            except Exception as e:
                error(f"加载账号文件失败: {e}\n{traceback.format_exc()}")

        # 3. 合并：settings 数据优先；若 config.json 不存在，从旧版 userinfo.json 回退 settings
        merged = dict(accounts_data)
        if settings_data:
            merged.update(settings_data)
        # 旧版兼容：如果 config.json 为空且 userinfo.json 含 settings 字段，自动迁移
        elif not self._settings_file.exists() and accounts_data:
            # 旧版 userinfo.json 可能包含 auto_exit / log_output_mode 等字段，自动作为 settings 使用
            pass  # merged 已包含 accounts_data 全部字段

        return AppConfig.from_dict(merged)

    def reload(self):
        """重新从文件加载配置（用于文件被外部修改后刷新）"""
        self._config = self._load_config()
        config_log(f"配置已重新加载: accounts={len(self._config.accounts)}")

    def save_config(self):
        """保存全部配置：账号写入 userinfo.json，设置写入 config.json"""
        try:
            # 保存账号数据 → userinfo.json
            self._accounts_file.parent.mkdir(parents=True, exist_ok=True)
            accounts_dict = self._config.to_accounts_dict()
            with open(self._accounts_file, 'w', encoding='utf-8') as f:
                json.dump(accounts_dict, f, ensure_ascii=False, indent=4)

            # 保存应用设置 → config.json
            self._settings_file.parent.mkdir(parents=True, exist_ok=True)
            settings_dict = self._config.to_settings_dict()
            with open(self._settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings_dict, f, ensure_ascii=False, indent=4)
        except Exception as e:
            error(f"保存配置失败: {e}\n{traceback.format_exc()}")

    def save_accounts(self):
        """仅保存账号数据到 userinfo.json（不触发 settings 写入）"""
        try:
            self._accounts_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._accounts_file, 'w', encoding='utf-8') as f:
                json.dump(self._config.to_accounts_dict(), f, ensure_ascii=False, indent=4)
        except Exception as e:
            error(f"保存账号文件失败: {e}\n{traceback.format_exc()}")

    def save_settings(self):
        """仅保存应用设置到 config.json（不触发 accounts 写入）"""
        try:
            self._settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._settings_file, 'w', encoding='utf-8') as f:
                json.dump(self._config.to_settings_dict(), f, ensure_ascii=False, indent=4)
        except Exception as e:
            error(f"保存设置文件失败: {e}\n{traceback.format_exc()}")

    @property
    def config(self) -> AppConfig:
        return self._config

    # ---- 便捷更新方法 ----

    def update_auto_exit(self, value: bool):
        self._config.auto_exit = value
        self.save_settings()

    def update_auto_login(self, value: bool):
        self._config.auto_login = value
        self.save_settings()

    def update_auto_start(self, value: bool):
        self._config.auto_start = value
        self.save_settings()

    def update_last_platform(self, value: int):
        self._config.last_platform = value
        self.save_settings()

    def update_last_room_id(self, value: str):
        self._config.set_last_room_id(self._config.last_platform, value)
        self.save_settings()

    def update_log_output_mode(self, value: str):
        self._config.log_output_mode = value
        self.save_settings()

    def update_log_level(self, value: int):
        self._config.log_level = value
        self.save_settings()

    def update_editor_font(self, english_family: str, chinese_family: str,
                           size: int, bold: bool, italic: bool):
        """更新编辑器字体配置"""
        self._config.editor_font = {
            "english_family": english_family,
            "chinese_family": chinese_family,
            "size": size,
            "bold": bold,
            "italic": italic,
        }
        self.save_settings()

    def update_account_room_id(self, uid: str, server_type: int, room_id: str):
        for acc in self._config.accounts:
            if acc.uid == uid and acc.server_type == server_type:
                acc.last_room_id = room_id
                self.save_accounts()
                return

    def add_account(self, account: Account):
        """添加/更新账号"""
        for i, acc in enumerate(self._config.accounts):
            if acc.uid == account.uid and acc.server_type == account.server_type:
                self._config.accounts[i] = account
                self.save_accounts()
                return
        self._config.accounts.append(account)
        self.save_accounts()

    def remove_account(self, uid: str, server_type: int):
        """删除账号"""
        self._config.accounts = [
            acc for acc in self._config.accounts
            if not (acc.uid == uid and acc.server_type == server_type)
        ]
        self.save_accounts()

    def update_account_notes(self, uid: str, server_type: int, notes: str):
        for acc in self._config.accounts:
            if acc.uid == uid and acc.server_type == server_type:
                acc.notes = notes
                self.save_accounts()
                return

    def update_account_game_type(self, uid: str, server_type: int, game_type: int):
        for acc in self._config.accounts:
            if acc.uid == uid and acc.server_type == server_type:
                acc.game_type = game_type
                self.save_accounts()
                return

    def update_account_mid(self, uid: str, server_type: int, mid: str):
        for acc in self._config.accounts:
            if acc.uid == uid and acc.server_type == server_type:
                acc.mid = mid
                self.save_accounts()
                return

    def get_accounts(self) -> list:
        return self._config.accounts

    def set_default_account(self, uid: str, server_type: int):
        self._config.default_account_uid = uid
        self._config.default_account_server_type = server_type
        self.save_accounts()

    def get_default_account(self) -> tuple:
        return self._config.default_account_uid, self._config.default_account_server_type

    def clear_default_account(self):
        self._config.default_account_uid = ""
        self._config.default_account_server_type = 1
        self.save_accounts()

    def is_default_account(self, uid: str, server_type: int) -> bool:
        return (self._config.default_account_uid == uid and
                self._config.default_account_server_type == server_type)
