"""
PyInstaller hook for pyzbar
自动收集 ctypes 加载的 DLL (libzbar-64.dll / libiconv.dll)
"""
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

# 收集所有子模块（pyzbar.pyzbar 等）
hiddenimports = collect_submodules("pyzbar")

# 收集 ctypes 加载的 DLL 到 _internal/pyzbar/
binaries = collect_dynamic_libs("pyzbar")
