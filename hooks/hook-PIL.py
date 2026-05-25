"""PyInstaller hook for PIL / Pillow"""
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("PIL")
