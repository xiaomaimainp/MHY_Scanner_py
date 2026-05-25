"""PyInstaller hook for curl_cffi"""
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("curl_cffi")
