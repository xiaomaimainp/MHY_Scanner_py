"""
版本与程序重启模块

本项目为自用分支，不做自动更新：
- 版本号采用「更新日期」命名（如 2026.10.22），与原 fork 的 1.0.x 迭代号区分
- 需要看新版时直接跳转仓库页面，不下载、不安装
"""
import sys
import os
import subprocess
import shutil
import traceback
from core.logger import update_log, error

# 版本号 = 更新日期（YYYY.MM.DD）。每次改动代码即改为当天日期。
VERSION = "2026.10.22"

# 本分支仓库地址
PROJECT_URL = "https://github.com/xiaomaimainp/MHY_Scanner_py"
PROJECT_ISSUES_URL = "https://github.com/xiaomaimainp/MHY_Scanner_py/issues"


class UpdateManager:
    """版本与程序重启管理（无自动更新）"""

    def __init__(self):
        self.script_path = os.path.abspath(__file__)
        self.main_script = os.path.join(os.path.dirname(os.path.dirname(self.script_path)), "main.py")
        self._current_version = None

    @property
    def current_version(self) -> str:
        """获取当前版本号（优先读取 QApplication.applicationVersion()，与 main.py 统一）"""
        if self._current_version is None:
            try:
                from PyQt6.QtWidgets import QApplication
                app = QApplication.instance()
                if app and app.applicationVersion():
                    self._current_version = app.applicationVersion()
                    return self._current_version
            except Exception:
                pass
            self._current_version = VERSION
        return self._current_version

    def restart_program(self):
        """重启程序，加载最新代码"""
        update_log("正在重启程序...")
        self._cleanup_temp_files()
        python = sys.executable
        try:
            subprocess.Popen(
                [python, self.main_script],
                cwd=os.path.dirname(self.main_script),
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
            )
            update_log("新进程已启动")
            return True
        except Exception as e:
            error(f"重启失败: {e}\n{traceback.format_exc()}")
            return False

    def _cleanup_temp_files(self):
        """清理编译缓存、临时文件"""
        temp_dir = os.path.dirname(self.main_script)
        temp_files = ["__pycache__", ".pytest_cache", "tempCodeRunnerFile.py"]
        for temp in temp_files:
            path = os.path.join(temp_dir, temp)
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                    update_log(f"已清理目录: {temp}")
                elif os.path.isfile(path):
                    os.remove(path)
                    update_log(f"已清理文件: {temp}")
            except Exception:
                pass

    def reload_module(self, module_name: str):
        """卸载并重新加载模块，用于热重载代码"""
        if module_name in sys.modules:
            del sys.modules[module_name]
            update_log(f"已卸载缓存模块：{module_name}")
        try:
            import importlib
            mod = importlib.import_module(module_name)
            update_log(f"模块重载完成：{module_name}")
            return mod
        except Exception as e:
            error(f"重载模块失败 {module_name}: {e}\n{traceback.format_exc()}")
            return None


# 全局单例
_update_manager = None


def get_update_manager() -> UpdateManager:
    global _update_manager
    if _update_manager is None:
        _update_manager = UpdateManager()
    return _update_manager


def restart_program() -> bool:
    return get_update_manager().restart_program()


def reload_module(module_name: str):
    return get_update_manager().reload_module(module_name)
