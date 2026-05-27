import sys
import os
import subprocess
import traceback

# 添加当前目录到 sys.path 以支持绝对导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ui.main_window import MainWindow
from core.logger import main_log, error


def main():
    """主函数"""
    # 必须在 QApplication 实例化之前设置，否则后续动态导入 QtWebEngineWidgets 会失败
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    # 启用高DPI支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)

    # 加载 Qt 中文翻译（汉化系统对话框：字体选择、文件对话框等）
    from PyQt6.QtCore import QTranslator, QLocale, QLibraryInfo
    translator = QTranslator()
    trans_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale.system(), "qtbase", "_", trans_path):
        app.installTranslator(translator)
    translator2 = QTranslator()
    if translator2.load(QLocale.system(), "qt", "_", trans_path):
        app.installTranslator(translator2)

    # 设置应用信息
    app.setApplicationName("MHY_Scanner")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("MHY")

    # 设置全局字体
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)

    # 创建并显示主窗口
    window = MainWindow()
    window.show()

    # 运行应用
    exit_code = app.exec()

    # 检查是否需要重启
    if window.should_restart:
        main_log("正在重启程序...")
        restart_program()
    sys.exit(exit_code)

def restart_program():
    """重启程序"""
    python = sys.executable  # 获取当前 Python 解释器路径
    script = os.path.abspath(__file__)  # 获取当前脚本路径
    try:
        # 使用新的进程启动程序
        subprocess.Popen([python, script])
    except Exception as e:
        error(f"重启失败: {e}\n{traceback.format_exc()}")

if __name__ == "__main__":
    main()
