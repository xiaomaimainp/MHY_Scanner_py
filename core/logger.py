"""
日志模块
统一管理项目的日志输出，支持控制台 / 文件 / 两者同时输出
日志文件最大 100KB，超限自动归档（重命名为时间戳.log）

输出模式由 GUI 设置菜单或配置文件控制，logger.py 不再维护默认值。
"""
import sys
import os
import re
import datetime
from pathlib import Path

# 最大日志文件大小（字节）
MAX_LOG_SIZE = 100 * 1024  # 100KB


def _get_log_dir() -> Path:
    """获取日志目录
    - 开发环境: 项目根目录下的 log/
    - 打包后: exe 所在目录下的 log/
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后，日志放在 exe 同级目录
        return Path(sys.executable).parent / "log"
    else:
        return Path(__file__).parent.parent / "log"


class OutputMode:
    """日志输出模式"""
    CONSOLE = "console"
    FILE = "file"


class LogLevel:
    """日志等级（数值越大越严重）"""
    DEBUG = 0
    INFO = 1
    WARN = 2
    ERROR = 3

    _VALUES = {0, 1, 2, 3}

    # 等级值 → 字符串名称（供 _log 内部使用）
    _NAME_MAP = {0: "DEBUG", 1: "INFO", 2: "WARN", 3: "ERROR"}

    @classmethod
    def is_valid(cls, value: int) -> bool:
        return value in cls._VALUES

    @classmethod
    def to_name(cls, value: int) -> str:
        """将等级数值转为字符串名称，不合法时回退 INFO"""
        return cls._NAME_MAP.get(value, "INFO")


class Logger:
    """日志工具类（单例）"""

    _instance = None
    _enabled = True
    _log_file = None
    _file_initialized = False  # 标记文件是否已初始化
    _output_mode = OutputMode.FILE  # 默认仅输出到文件
    _log_level = LogLevel.INFO  # 默认输出 INFO 及以上等级的日志

    # ---- 输出模式设置 ----

    @classmethod
    def set_output_mode(cls, mode: str):
        """
        设置日志输出模式
        :param mode: "console"（仅控制台）/ "file"（仅文件）
        """
        if mode in (OutputMode.CONSOLE, OutputMode.FILE):
            cls._output_mode = mode

    @classmethod
    def get_output_mode(cls) -> str:
        """获取当前输出模式"""
        return cls._output_mode

    @classmethod
    def set_log_level(cls, level: int):
        """
        设置日志等级
        :param level: LogLevel.DEBUG / INFO / WARN / ERROR
        """
        if LogLevel.is_valid(level):
            cls._log_level = level

    @classmethod
    def get_log_level(cls) -> int:
        """获取当前日志等级"""
        return cls._log_level

    # ---- 文件初始化 / 归档 / 清理 ----

    @classmethod
    def _init_file(cls):
        """初始化日志目录和活跃日志文件"""
        try:
            log_dir = _get_log_dir()
            log_dir.mkdir(parents=True, exist_ok=True)
            cls._log_file = str(log_dir / "mhy_scanner.log")
        except Exception:
            cls._log_file = None

    @classmethod
    def _rotate_file(cls):
        """检查日志文件大小，超过 100KB 则归档（重命名为时间戳.log）"""
        if not cls._log_file:
            return
        try:
            file_path = Path(cls._log_file)
            if file_path.exists() and file_path.stat().st_size >= MAX_LOG_SIZE:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                archive_path = file_path.parent / f"mhy_scanner_{timestamp}.log"
                file_path.rename(archive_path)
                # 归档后清理过期日志
                cls._cleanup_old_logs()
        except Exception:
            pass

    @classmethod
    def _cleanup_old_logs(cls):
        """清理超过 7 天的归档日志（仅清理带时间戳的归档文件）"""
        try:
            log_dir = _get_log_dir()
            if not log_dir.exists():
                return
            cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
            archive_pattern = re.compile(r"mhy_scanner_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.log")
            for f in log_dir.iterdir():
                if not f.is_file():
                    continue
                # 只清理归档文件（跳过活跃的 mhy_scanner.log）
                if not archive_pattern.match(f.name):
                    continue
                try:
                    mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime < cutoff:
                        f.unlink()
                except Exception:
                    pass
        except Exception:
            pass

    # ---- 启用 / 禁用 ----

    @classmethod
    def enable(cls):
        cls._enabled = True

    @classmethod
    def disable(cls):
        cls._enabled = False

    # ---- 核心输出 ----

    @classmethod
    def _log(cls, level: str, tag: str, msg: str, console_only: bool = False):
        if not cls._enabled:
            return
        # 级别过滤：低于当前阈值的日志不输出
        level_map = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
        if level_map.get(level, 1) < cls._log_level:
            return
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        tag_part = f"[{tag}]" if tag != level else ""
        line = f"[{timestamp}][{level}]{tag_part} {msg}"

        if console_only:
            # 仅控制台输出，不写入文件
            print(line, flush=True)
            return

        # 控制台输出
        if cls._output_mode == OutputMode.CONSOLE:
            print(line, flush=True)

        # 文件输出
        if cls._output_mode == OutputMode.FILE:
            cls._write_file(line)

    @classmethod
    def _write_file(cls, line: str):
        """写入日志文件（写入前检查文件大小，超限自动归档）
        
        首次写入时懒初始化日志目录和文件路径。
        """
        try:
            if not cls._file_initialized:
                cls._init_file()
                cls._file_initialized = True
            cls._rotate_file()
            if cls._log_file:
                with open(cls._log_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            pass

    @classmethod
    def debug(cls, tag: str, msg: str):
        cls._log("DEBUG", tag, msg)

    @classmethod
    def info(cls, tag: str, msg: str):
        cls._log("INFO", tag, msg)

    @classmethod
    def warn(cls, tag: str, msg: str):
        cls._log("WARN", tag, msg)

    @classmethod
    def error(cls, tag: str, msg: str):
        cls._log("ERROR", tag, msg)

    # ---- 预定义标签（支持 level 参数实现严格分层） ----

    @classmethod
    def screen_scanner(cls, msg: str, level: int = LogLevel.INFO):
        cls._log(LogLevel.to_name(level), "ScreenScanner", msg)

    @classmethod
    def qr_login(cls, msg: str, level: int = LogLevel.INFO):
        cls._log(LogLevel.to_name(level), "QRLogin", msg)

    @classmethod
    def api(cls, msg: str, level: int = LogLevel.INFO):
        cls._log(LogLevel.to_name(level), "API", msg)

    @classmethod
    def polling(cls, msg: str, level: int = LogLevel.INFO):
        cls._log(LogLevel.to_name(level), "Polling", msg)

    @classmethod
    def bilibili(cls, msg: str, level: int = LogLevel.INFO, console_only: bool = False):
        cls._log(LogLevel.to_name(level), "BiliBili", msg, console_only=console_only)

    @classmethod
    def main(cls, msg: str, level: int = LogLevel.INFO):
        cls._log(LogLevel.to_name(level), "Main", msg)

    @classmethod
    def gui(cls, msg: str, level: int = LogLevel.INFO):
        """GUI消息提示（与QMessageBox配合使用）"""
        cls._log(LogLevel.to_name(level), "GUI", msg)

    @classmethod
    def config(cls, msg: str, level: int = LogLevel.INFO):
        cls._log(LogLevel.to_name(level), "Config", msg)

    @classmethod
    def update(cls, msg: str, level: int = LogLevel.INFO):
        cls._log(LogLevel.to_name(level), "Update", msg)

    @classmethod
    def douyin(cls, msg: str, level: int = LogLevel.INFO, console_only: bool = False):
        cls._log(LogLevel.to_name(level), "DouyinLive", msg, console_only=console_only)

    @classmethod
    def bili_sdk(cls, msg: str, level: int = LogLevel.INFO):
        cls._log(LogLevel.to_name(level), "BSGameSDK", msg)


# ---- 常用快捷函数 ----

def scanner_log(msg: str, level: int = LogLevel.INFO):
    Logger.screen_scanner(msg, level)

def qr_log(msg: str, level: int = LogLevel.INFO):
    Logger.qr_login(msg, level)

def api_log(msg: str, level: int = LogLevel.INFO):
    Logger.api(msg, level)

def poll_log(msg: str, level: int = LogLevel.INFO):
    Logger.polling(msg, level)

def bili_log(msg: str, level: int = LogLevel.INFO, console_only: bool = False):
    Logger.bilibili(msg, level, console_only=console_only)

def main_log(msg: str, level: int = LogLevel.INFO):
    Logger.main(msg, level)

def gui_log(msg: str, level: int = LogLevel.INFO):
    Logger.gui(msg, level)

def config_log(msg: str, level: int = LogLevel.INFO):
    Logger.config(msg, level)

def update_log(msg: str, level: int = LogLevel.INFO):
    Logger.update(msg, level)

def douyin_log(msg: str, level: int = LogLevel.INFO, console_only: bool = False):
    Logger.douyin(msg, level, console_only=console_only)

def bsgsdk_log(msg: str, level: int = LogLevel.INFO):
    Logger.bili_sdk(msg, level)

def geetest_log(msg: str, level: int = LogLevel.INFO):
    Logger.geetest(msg, level)

def debug(msg: str):
    Logger.debug("DEBUG", msg)

def info(msg: str):
    Logger.info("INFO", msg)

def warn(msg: str):
    Logger.warn("WARN", msg)

def error(msg: str):
    Logger.error("ERROR", msg)
