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

# Windows 下可能缺少 SSL 证书，禁用证书验证
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class UpdateManager:
    """热更新管理器"""

    # GitHub Release API（获取最新版本信息）
    GITHUB_API_URL = "https://api.github.com/repos/MR-LIYA/MHY_Scanner/releases?per_page=1"
    # 下载地址
    DOWNLOAD_URL = "https://github.com/MR-LIYA/MHY_Scanner/releases/download/main/MHY_Scanner.exe"

    def __init__(self):
        self.script_path = os.path.abspath(__file__)
        self.main_script = os.path.join(os.path.dirname(os.path.dirname(self.script_path)), "main.py")
        self._current_version = None

    @property
    def current_version(self) -> str:
        """从 __init__.py 获取当前版本号"""
        if self._current_version is None:
            try:
                from __init__ import __version__
                self._current_version = __version__
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
            "download_url": self.DOWNLOAD_URL,
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

    def download_and_apply_update(self, progress_callback=None) -> bool:
        """
        下载新版本 exe 并替换当前程序。
        替换策略：创建批处理脚本→退出程序→脚本完成替换→重启。
        """
        exe_path = sys.executable
        exe_dir = os.path.dirname(exe_path)
        exe_name = os.path.basename(exe_path)

        # 下载到临时文件
        tmp_path = os.path.join(exe_dir, f"{exe_name}.update")
        update_log(f"开始下载更新: {self.DOWNLOAD_URL}")

        try:
            resp = requests.get(self.DOWNLOAD_URL, stream=True, timeout=120, verify=False)
            if resp.status_code != 200:
                error(f"下载失败，HTTP {resp.status_code}")
                return False

            total = int(resp.headers.get("content-length", 0))
            downloaded = 0

            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            progress_callback(int(downloaded / total * 100))

            update_log(f"下载完成: {tmp_path} ({downloaded} bytes)")

            # 生成替换批处理脚本
            bat_path = os.path.join(exe_dir, "_updater.bat")
            backup_path = os.path.join(exe_dir, f"{exe_name}.old")
            # Windows batch: 等待原进程退出后替换
            bat_content = (
                f'@echo off\n'
                f'echo Waiting for update...\n'
                f'timeout /t 2 /nobreak >nul\n'
                f'if exist "{backup_path}" del /f "{backup_path}"\n'
                f'rename "{exe_path}" "{exe_name}.old"\n'
                f'rename "{tmp_path}" "{exe_name}"\n'
                f'if exist "{exe_path}" (\n'
                f'  echo Update complete, restarting...\n'
                f'  start "" "{exe_path}"\n'
                f') else (\n'
                f'  echo Update failed, restoring backup...\n'
                f'  rename "{backup_path}" "{exe_name}"\n'
                f'  start "" "{exe_path}"\n'
                f')\n'
                f'del "%~f0"\n'
            )

            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat_content)

            update_log("替换脚本已生成，即将退出并更新...")
            subprocess.Popen(
                bat_path,
                shell=True,
                cwd=exe_dir,
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


def download_and_apply_update(progress_callback=None) -> bool:
    """快捷函数：下载并应用更新"""
    return get_update_manager().download_and_apply_update(progress_callback)
