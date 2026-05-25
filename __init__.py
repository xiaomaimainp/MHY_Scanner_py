"""
MHY_Scanner - 米哈游扫码登录器 Python版
基于 PyQt6 + OpenCV 实现
支持：崩坏3、原神、星穹铁道、绝区零（官服/BiliBili服）
"""

from ui.main_window import MainWindow
from ui.login_window import LoginWindow
from api import MhyApi, GameType, ServerType, ScanRet
from scanner import ScreenScanner, StreamScanner, is_mhy_qrcode, extract_ticket
from ui.account_manager import AccountManager
from core.config import ConfigManager, Account
from scanner import LivePlatform, get_live_info, LiveStreamStatus
from core.logger import Logger, scanner_log, qr_log, api_log, poll_log, bili_log, main_log, gui_log, debug, info, warn, error

__version__ = "1.0.0"
__all__ = [
    "MainWindow",
    "LoginWindow",
    "MhyApi",
    "GameType",
    "ServerType",
    "ScanRet",
    "ScreenScanner",
    "StreamScanner",
    "AccountManager",
    "ConfigManager",
    "Account",
    "LivePlatform",
    "get_live_info",
    "LiveStreamStatus",
    "is_mhy_qrcode",
    "extract_ticket",
    "Logger",
    "scanner_log",
    "qr_log",
    "api_log",
    "poll_log",
    "bili_log",
    "main_log",
    "gui_log",
    "debug",
    "info",
    "warn",
    "error",
]
