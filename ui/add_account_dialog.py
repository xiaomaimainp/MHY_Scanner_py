"""
添加账号对话框
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QFormLayout,
    QMessageBox
)
from PyQt6.QtCore import Qt
from api import GameType, ServerType
from core.logger import gui_log, LogLevel


class AddAccountDialog(QDialog):
    """添加账号对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加账号")
        self.setMinimumWidth(400)
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # 表单布局
        form_layout = QFormLayout()
        
        # UID
        self.uid_edit = QLineEdit()
        self.uid_edit.setPlaceholderText("输入用户UID")
        form_layout.addRow("UID:", self.uid_edit)
        
        # 用户名
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("输入用户名")
        form_layout.addRow("用户名:", self.name_edit)
        
        # 游戏选择
        self.game_combo = QComboBox()
        self.game_combo.addItems(["崩坏3", "原神", "星穹铁道", "绝区零"])
        form_layout.addRow("游戏:", self.game_combo)
        
        # 服务器选择
        self.server_combo = QComboBox()
        self.server_combo.addItems(["官服", "BiliBili服"])
        form_layout.addRow("服务器:", self.server_combo)
        
        # Token
        self.token_edit = QLineEdit()
        self.token_edit.setPlaceholderText("输入Token (game_token或stoken)")
        form_layout.addRow("Token:", self.token_edit)
        
        # MID (官服)
        self.mid_edit = QLineEdit()
        self.mid_edit.setPlaceholderText("MID (仅官服需要)")
        form_layout.addRow("MID:", self.mid_edit)
        
        layout.addLayout(form_layout)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        
        self.ok_button = QPushButton("确定")
        self.ok_button.clicked.connect(self.on_ok)
        button_layout.addWidget(self.ok_button)
        
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
    
    def on_ok(self):
        """确定按钮点击"""
        uid = self.uid_edit.text().strip()
        name = self.name_edit.text().strip()
        token = self.token_edit.text().strip()

        if not uid:
            gui_log("请输入UID", LogLevel.WARN)
            QMessageBox.warning(self, "输入错误", "请输入UID")
            return

        if not name:
            gui_log("请输入用户名", LogLevel.WARN)
            QMessageBox.warning(self, "输入错误", "请输入用户名")
            return

        if not token:
            gui_log("请输入Token", LogLevel.WARN)
            QMessageBox.warning(self, "输入错误", "请输入Token")
            return

        self.accept()
    
    def get_uid(self) -> str:
        return self.uid_edit.text().strip()
    
    def get_name(self) -> str:
        return self.name_edit.text().strip()
    
    def get_token(self) -> str:
        return self.token_edit.text().strip()
    
    def get_game_type(self) -> GameType:
        game_map = {
            0: GameType.Honkai3,
            1: GameType.Genshin,
            2: GameType.HonkaiStarRail,
            3: GameType.ZenlessZoneZero
        }
        return game_map.get(self.game_combo.currentIndex(), GameType.Genshin)
    
    def get_server_type(self) -> ServerType:
        if self.server_combo.currentIndex() == 1:
            return ServerType.BiliBili
        return ServerType.Official
    
    def get_mid(self) -> str:
        return self.mid_edit.text().strip()
