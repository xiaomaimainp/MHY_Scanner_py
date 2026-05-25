"""
热更新模块
处理程序的热更新、重启等功能
"""
import sys
import os
import subprocess
import shutil
import traceback
import requests
from datetime import datetime
from core.logger import update_log, error, LogLevel


class UpdateManager:
    """热更新管理器"""

    def __init__(self):
        self.update_url = "https://github.com/MR-LIYA/user/releases/tag/v1.0.1/MHY_Scanner.exe"  # 更新检查URL
        self.script_path = os.path.abspath(__file__)
        self.main_script = os.path.join(os.path.dirname(os.path.dirname(self.script_path)), "main.py")
        self._current_version = None  # 延迟加载

    @property
    def current_version(self) -> str:
        """从 main.py 获取当前版本"""
        if self._current_version is None:
            import re
            try:
                with open(self.main_script, "r", encoding="utf-8") as f:
                    content = f.read()
                match = re.search(r'setApplicationVersion\(["\']([^"\']+)["\']', content)
                self._current_version = match.group(1) if match else "1.0.0"
            except Exception:
                self._current_version = "1.0.0"
        return self._current_version

    def restart_program(self):
        """
        重启程序（加载最新代码）
        用于代码修改后的热更新
        """
        update_log("正在重启程序...")

        # 清理临时文件
        self._cleanup_temp_files()

        python = sys.executable
        try:
            # 启动新的进程
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
        """清理临时文件"""
        temp_dir = os.path.dirname(self.main_script)
        temp_files = [
            "__pycache__",
            ".pytest_cache",
            "tempCodeRunnerFile.py",
        ]
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

    def check_for_updates(self) -> dict:
        """
        检查更新（需要配合远程服务器）
        返回: {"has_update": bool, "version": str, "description": str}
        """
        result = {
            "has_update": False,
            "version": self.current_version,
            "description": ""
        }

        if not self.update_url:
            update_log("未配置更新检查URL", LogLevel.WARN)
            return result

        try:
            response = requests.get(self.update_url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                latest_version = data.get("version", self.current_version)
                if self._compare_version(latest_version, self.current_version) > 0:
                    result["has_update"] = True
                    result["version"] = latest_version
                    result["description"] = data.get("description", "")
        except Exception as e:
            error(f"检查更新失败: {e}")

        return result

    def _compare_version(self, v1: str, v2: str) -> int:
        """比较版本号: v1 > v2 返回 1, v1 < v2 返回 -1, 相等返回 0"""
        def parse(v):
            return [int(x) for x in v.split(".")]

        v1_parts = parse(v1)
        v2_parts = parse(v2)

        for i in range(max(len(v1_parts), len(v2_parts))):
            p1 = v1_parts[i] if i < len(v1_parts) else 0
            p2 = v2_parts[i] if i < len(v2_parts) else 0
            if p1 > p2:
                return 1
            elif p1 < p2:
                return -1
        return 0

    def reload_module(self, module_name: str):
        """
        重新加载指定模块
        用于更新某个模块的代码
        """
        if module_name in sys.modules:
            # 删除模块缓存
            del sys.modules[module_name]
            update_log(f"已卸载模块: {module_name}")

        # 重新导入
        try:
            import importlib
            mod = importlib.import_module(module_name)
            update_log(f"已重新加载模块: {module_name}")
            return mod
        except Exception as e:
            error(f"加载模块失败: {e}\n{traceback.format_exc()}")
            return None


# 全局单例
_update_manager = None


def get_update_manager() -> UpdateManager:
    """获取更新管理器单例"""
    global _update_manager
    if _update_manager is None:
        _update_manager = UpdateManager()
    return _update_manager


def restart_program() -> bool:
    """快捷函数：重启程序"""
    return get_update_manager().restart_program()


def check_for_updates() -> dict:
    """快捷函数：检查更新"""
    return get_update_manager().check_for_updates()


def reload_module(module_name: str):
    """快捷函数：重新加载模块"""
    return get_update_manager().reload_module(module_name)
