"""
core 包 - 基础设施层
提供日志系统和配置管理
"""
from .logger import (
    Logger, OutputMode, LogLevel,
    scanner_log, qr_log, api_log, poll_log, bili_log,
    main_log, gui_log, config_log, update_log, douyin_log,
    bsgsdk_log, geetest_log, debug, info, warn, error,
)
from .config import (
    ConfigManager, Account, AppConfig,
    get_base_dir, get_accounts_file_path, get_settings_file_path,
)
