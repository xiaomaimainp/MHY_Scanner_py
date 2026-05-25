"""
账号管理模块
"""
from typing import List, Optional, Callable
from PyQt6.QtCore import QObject, pyqtSignal
from core.config import ConfigManager, Account
from api import GameType, ServerType


class AccountManager(QObject):
    """账号管理器"""
    
    account_added = pyqtSignal(dict)      # 账号添加信号
    account_removed = pyqtSignal(str)    # 账号移除信号(uid)
    account_updated = pyqtSignal(dict)   # 账号更新信号
    
    # 游戏名称映射
    GAME_NAMES = {
        GameType.Honkai3: "崩坏3",
        GameType.Genshin: "原神",
        GameType.HonkaiStarRail: "星穹铁道",
        GameType.ZenlessZoneZero: "绝区零",
    }
    
    # 服务器名称映射
    SERVER_NAMES = {
        ServerType.Official: "官服",
        ServerType.BiliBili: "BiliBili服",
    }
    
    def __init__(self):
        super().__init__()
        self._config = ConfigManager()
    
    def get_accounts(self) -> List[Account]:
        """获取所有账号"""
        return self._config.get_accounts()
    
    def add_account(self, uid: str, name: str, token: str, 
                    server_type: ServerType = ServerType.Official,
                    game_type: GameType = GameType.Genshin,
                    mid: str = "", notes: str = ""):
        """
        添加账号
        
        Args:
            uid: 用户ID
            name: 用户名
            token: 令牌(game_token或stoken)
            server_type: 服务器类型
            game_type: 游戏类型
            mid: mid (官服用)
            notes: 备注
        """
        account = Account(
            uid=uid,
            name=name,
            token=token,
            mid=mid,
            server_type=int(server_type),
            game_type=int(game_type),
            notes=notes,
            last_login=""
        )
        
        self._config.add_account(account)
        self.account_added.emit({
            "uid": uid,
            "name": name,
            "server_type": int(server_type),
            "game_type": int(game_type)
        })
    
    def remove_account(self, uid: str, server_type: int):
        """删除账号"""
        self._config.remove_account(uid, server_type)
        self.account_removed.emit(uid)
    
    def update_notes(self, uid: str, server_type: int, notes: str):
        """更新备注"""
        self._config.update_account_notes(uid, server_type, notes)

    def update_game_type(self, uid: str, server_type: int, game_type: GameType):
        """更新游戏类型"""
        self._config.update_account_game_type(uid, server_type, int(game_type))

    def update_mid(self, uid: str, server_type: int, mid: str):
        """更新账号MID"""
        self._config.update_account_mid(uid, server_type, mid)
    
    def get_account(self, uid: str, server_type: int) -> Optional[Account]:
        """获取指定账号"""
        for acc in self._config.get_accounts():
            if acc.uid == uid and acc.server_type == server_type:
                return acc
        return None
    
    def get_game_accounts(self, game_type: GameType) -> List[Account]:
        """获取指定游戏的账号"""
        accounts = []
        for acc in self._config.get_accounts():
            if acc.game_type == int(game_type):
                accounts.append(acc)
        return accounts
    
    def get_server_accounts(self, server_type: ServerType) -> List[Account]:
        """获取指定服务器的账号"""
        accounts = []
        for acc in self._config.get_accounts():
            if acc.server_type == int(server_type):
                accounts.append(acc)
        return accounts
    
    def get_game_name(self, game_type: GameType) -> str:
        """获取游戏名称"""
        return self.GAME_NAMES.get(game_type, "未知游戏")
    
    def get_server_name(self, server_type: ServerType) -> str:
        """获取服务器名称"""
        return self.SERVER_NAMES.get(server_type, "未知服务器")
    
    def format_account_info(self, account: Account) -> str:
        """格式化账号信息"""
        game_name = self.get_game_name(GameType(account.game_type))
        server_name = self.get_server_name(ServerType(account.server_type))
        return f"{account.name} ({game_name} {server_name})"
    
    def to_table_rows(self) -> List[dict]:
        """转换为表格行数据"""
        rows = []
        for acc in self._config.get_accounts():
            game_name = self.get_game_name(GameType(acc.game_type))
            server_name = self.get_server_name(ServerType(acc.server_type))
            rows.append({
                "uid": acc.uid,
                "name": acc.name,
                "game": game_name,
                "server": server_name,
                "notes": acc.notes,
                "server_type": acc.server_type
            })
        return rows
