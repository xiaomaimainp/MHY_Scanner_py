"""
热更新模块
处理程序的热更新、重启等功能
"""
import sys
import os
import subprocess
import shutil
import traceback
import tempfile
import requests
from core.logger import update_log, error, LogLevel

# Windows 下可能缺少 SSL 证书，禁用证书验证
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

VERSION = "1.0.3"

class UpdateManager:
    """热更新管理器"""

    # GitHub Release API（获取最新版本信息）
    GITHUB_API_URL = "https://api.github.com/repos/MR-LIYA/MHY_Scanner/releases?per_page=1"
    # 安装程序下载地址
    INSTALLER_URL = "https://github.com/MR-LIYA/MHY_Scanner/releases/download/main/MHY_Scanner_Setup.exe"

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
            try:
                from __init__ import __version__
                self._current_version = __version__
            except Exception:
                self._current_version = VERSION
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
        通过 GitHub API 检查更新。
        Release title 格式为 V1.0.0 / V1.0.1 等，自动剥离前缀 V 比较版本号。
        返回: {"has_update": bool, "version": str, "description": str, "download_url": str}
        """
        result = {
            "has_update": False,
            "no_release": False,
            "check_failed": False,
            "current_version": self.current_version,
            "latest_version": "",
            "description": "",
            "download_url": "",
        }

        try:
            response = requests.get(self.GITHUB_API_URL, timeout=30, verify=False)
            if response.status_code != 200:
                update_log(f"GitHub API 返回状态码: {response.status_code}", LogLevel.WARN)
                return result

            releases = response.json()
            if not releases or not isinstance(releases, list):
                update_log("GitHub 仓库尚未发布任何 Release 版本，跳过更新检查", LogLevel.INFO)
                result["no_release"] = True
                return result

            release = releases[0]
            # Tag 只有 main，版本号写在 Release Title 里（如 V1.0.1）
            tag = release.get("name", "") or release.get("tag_name", "")
            if not tag:
                update_log("未能从 Release 信息中解析版本号", LogLevel.WARN)
                return result

            latest_version = tag.lstrip("Vv")
            description = release.get("body", "") or release.get("name", "")

            # 获取下载链接（优先从 release assets 中提取）
            assets = release.get("assets", [])
            if assets:
                result["download_url"] = assets[0].get("browser_download_url", "")
                # 如果 assets 中没有 .exe，回退到硬编码 URL
                if not any(a.get("name", "").endswith(".exe") for a in assets):
                    result["download_url"] = self.INSTALLER_URL
            else:
                result["download_url"] = self.INSTALLER_URL

            # 校验是否为合法版本号格式（x.x.x）
            if not self._is_valid_version(latest_version):
                update_log(f"无法解析版本号: {tag}", LogLevel.WARN)
                return result
            result["latest_version"] = latest_version
            result["description"] = description

            update_log(f"当前版本: {self.current_version}, 最新版本: {latest_version}")
            if self._compare_version(latest_version, self.current_version) > 0:
                result["has_update"] = True
                update_log(f"发现新版本: {latest_version}")
        except Exception as e:
            error(f"检查更新失败: {e}")
            result["check_failed"] = True

        return result

    def download_and_apply_update(self, download_url: str = "", progress_callback=None) -> bool:
        """
        下载安装程序 → 启动安装程序 → 退出当前程序
        安装程序会自行完成安装/覆盖，无需额外处理。
        """
        url = download_url or self.INSTALLER_URL
        update_log(f"开始下载安装程序: {url}")

        try:
            resp = requests.get(url, stream=True, timeout=600, verify=False)
            if resp.status_code != 200:
                error(f"下载失败，HTTP {resp.status_code}")
                return False

            # 下载到系统临时目录
            installer_name = "MHY_Scanner_Setup.exe"
            installer_path = os.path.join(tempfile.gettempdir(), installer_name)

            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            with open(installer_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            progress_callback(int(downloaded / total * 100))

            update_log(f"安装程序下载完成: {installer_path} ({downloaded} bytes)")
            update_log("启动安装程序，程序即将退出...")

            # 启动安装程序（交给用户交互安装，不使用静默参数）
            subprocess.Popen(
                [installer_path],
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0,
            )
            return True

        except Exception as e:
            error(f"下载更新失败: {e}\n{traceback.format_exc()}")
            return False

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

    def _is_valid_version(self, version: str) -> bool:
        """校验是否为合法版本号格式（如 1.0.0）"""
        try:
            parts = version.split(".")
            return len(parts) >= 2 and all(part.isdigit() for part in parts)
        except Exception:
            return False

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


def download_and_apply_update(download_url: str = "", progress_callback=None) -> bool:
    """快捷函数：下载并应用更新"""
    return get_update_manager().download_and_apply_update(download_url, progress_callback)
