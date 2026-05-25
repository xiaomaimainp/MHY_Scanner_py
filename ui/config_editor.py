"""
轻量化内置文本编辑器（类似记事本）
- 多选项卡，每个选项卡对应 Config 目录下的一个配置文件
- 支持编辑和保存
"""
import json
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPlainTextEdit, QPushButton, QMessageBox,
    QMenuBar, QStatusBar, QMenu, QWidget,
    QFontComboBox, QSpinBox, QCheckBox,
    QGroupBox, QLabel, QFrame, QDialogButtonBox,
    QTextEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QRect, QSize
from PyQt6.QtGui import (
    QFont, QAction, QTextCursor, QPainter, QColor,
    QTextCharFormat, QTextOption,
)
from core.logger import gui_log, LogLevel
from core.config import ConfigManager


class LineNumberArea(QWidget):
    """行号区域"""

    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.line_number_area_paint_event(event)


class ChineseTextEdit(QPlainTextEdit):
    """支持行号显示和智能缩进的 QPlainTextEdit 子类"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._show_line_numbers = True

        self._line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)

        self._update_line_number_area_width(0)
        self._highlight_current_line()

    # ── 行号 ──

    def line_number_area_width(self) -> int:
        """计算行号区域宽度"""
        if not self._show_line_numbers:
            return 0
        digits = max(1, len(str(max(1, self.blockCount()))))
        space = 10 + self.fontMetrics().horizontalAdvance('9') * digits
        return space

    def set_line_numbers_visible(self, visible: bool):
        """显示/隐藏行号"""
        self._show_line_numbers = visible
        self._update_line_number_area_width(0)

    def is_line_numbers_visible(self) -> bool:
        return self._show_line_numbers

    def _update_line_number_area_width(self, _new_block_count: int):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect: QRect, dy: int):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(),
                                          self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(),
                  self.line_number_area_width(), cr.height())
        )

    def line_number_area_paint_event(self, event):
        if not self._show_line_numbers:
            return
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor("#F0F0F0"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current_block = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                if block_number == current_block:
                    painter.setPen(QColor("#000000"))
                else:
                    painter.setPen(QColor("#999999"))
                painter.drawText(
                    0, top,
                    self._line_number_area.width() - 4,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, number
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    # ── 当前行高亮 ──

    def _highlight_current_line(self):
        """高亮当前行"""
        extra_selections = []

        if self._show_line_numbers:
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor("#E8F0FE"))
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)

        self.setExtraSelections(extra_selections)

    # ── 智能缩进 ──

    def keyPressEvent(self, event):
        """Enter 键智能缩进"""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            cursor = self.textCursor()
            # 获取当前行文本（光标前的内容）
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock,
                                QTextCursor.MoveMode.KeepAnchor)
            current_line = cursor.selectedText()

            # 提取前导空白
            indent = self._extract_indent(current_line)

            # 检查当前行末字符，决定是否增加缩进
            stripped = current_line.strip()
            if stripped:
                last_char = stripped[-1]
                if last_char in '{[:':
                    indent += '    '  # 4 空格

            # 插入换行 + 缩进
            cursor.clearSelection()
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)

            # 检查下一字符，如果是配对的闭合符号则自动对齐
            original_pos = cursor.position()
            cursor.movePosition(QTextCursor.MoveOperation.NextCharacter,
                                QTextCursor.MoveMode.KeepAnchor, 1)
            next_char = cursor.selectedText()
            cursor.setPosition(original_pos)

            cursor.insertText('\n' + indent)

            # 如果闭合符号 }] 紧跟在缩进后，取消缩进一级
            if next_char in '}]' and len(indent) >= 4:
                cursor.movePosition(QTextCursor.MoveOperation.PreviousCharacter,
                                    QTextCursor.MoveMode.MoveAnchor, 4)
                cursor.deleteChar()

            self.setTextCursor(cursor)
            return

        super().keyPressEvent(event)

    @staticmethod
    def _extract_indent(line: str) -> str:
        """从行文本中提取前导空白"""
        indent = ''
        for ch in line:
            if ch in ' \t':
                indent += ch
            else:
                break
        return indent

    # ── 右键菜单（保持汉化）──

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        translations = {
            "&Undo": "撤销(&U)",
            "&Redo": "重做(&R)",
            "Cu&t": "剪切(&T)",
            "&Copy": "复制(&C)",
            "&Paste": "粘贴(&P)",
            "&Delete": "删除(&D)",
            "Select &All": "全选(&A)",
        }
        for action in menu.actions():
            if action.text() in translations:
                action.setText(translations[action.text()])
            elif action.text() == "&Undo":
                action.setText("撤销(&U)")
            elif action.text() == "&Redo":
                action.setText("重做(&R)")
        menu.exec(event.globalPos())


class FontSettingsDialog(QDialog):
    """中英文字体统一设置对话框"""

    def __init__(self, english_family: str, chinese_family: str,
                 size: int, bold: bool, italic: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("字体设置")
        self.setMinimumWidth(440)
        self.setModal(True)

        self.english_family = english_family
        self.chinese_family = chinese_family
        self.font_size = size
        self.font_bold = bold
        self.font_italic = italic

        layout = QVBoxLayout()
        self.setLayout(layout)

        # ── 英文字体 ──
        eng_layout = QHBoxLayout()
        eng_layout.addWidget(QLabel("英文字体:"))
        self.cmb_english = QFontComboBox()
        self.cmb_english.setCurrentFont(QFont(english_family))
        self.cmb_english.currentFontChanged.connect(self._on_change)
        eng_layout.addWidget(self.cmb_english, 1)
        layout.addLayout(eng_layout)

        # ── 中文字体 ──
        chs_layout = QHBoxLayout()
        chs_layout.addWidget(QLabel("中文字体:"))
        self.cmb_chinese = QFontComboBox()
        self.cmb_chinese.setCurrentFont(QFont(chinese_family))
        self.cmb_chinese.currentFontChanged.connect(self._on_change)
        chs_layout.addWidget(self.cmb_chinese, 1)
        layout.addLayout(chs_layout)

        # ── 字号、加粗、倾斜 ──
        style_layout = QHBoxLayout()
        style_layout.addWidget(QLabel("字号:"))
        self.spin_size = QSpinBox()
        self.spin_size.setRange(6, 72)
        self.spin_size.setValue(size)
        self.spin_size.valueChanged.connect(self._on_change)
        style_layout.addWidget(self.spin_size)
        style_layout.addStretch()

        self.chk_bold = QCheckBox("加粗(&B)")
        self.chk_bold.setChecked(bold)
        self.chk_bold.toggled.connect(self._on_change)
        style_layout.addWidget(self.chk_bold)

        self.chk_italic = QCheckBox("倾斜(&I)")
        self.chk_italic.setChecked(italic)
        self.chk_italic.toggled.connect(self._on_change)
        style_layout.addWidget(self.chk_italic)

        layout.addLayout(style_layout)

        # ── 预览 ──
        preview_group = QGroupBox("预览")
        pv_layout = QVBoxLayout()
        preview_group.setLayout(pv_layout)

        self.preview_label = QLabel("ABCabc 你好世界 0123456789")
        self.preview_label.setMinimumHeight(50)
        self.preview_label.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_preview()
        pv_layout.addWidget(self.preview_label)

        layout.addWidget(preview_group)

        # ── 按钮 ──
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _on_change(self):
        self._update_preview()

    def _update_preview(self):
        font = QFont()
        font.setFamilies([
            self.cmb_english.currentFont().family(),
            self.cmb_chinese.currentFont().family(),
        ])
        font.setPointSize(self.spin_size.value())
        font.setBold(self.chk_bold.isChecked())
        font.setItalic(self.chk_italic.isChecked())
        self.preview_label.setFont(font)

    def _on_accept(self):
        self.english_family = self.cmb_english.currentFont().family()
        self.chinese_family = self.cmb_chinese.currentFont().family()
        self.font_size = self.spin_size.value()
        self.font_bold = self.chk_bold.isChecked()
        self.font_italic = self.chk_italic.isChecked()
        self.accept()


class ConfigEditor(QDialog):
    """内置配置文件编辑器"""

    file_saved = pyqtSignal(str)  # 文件保存后发射 (filepath)

    def __init__(self, base_dir: Path, parent: Optional[QDialog] = None):
        super().__init__(parent)
        self._base_dir = base_dir
        self._config_dir = base_dir / "Config"
        self._modified_flags: dict[str, bool] = {}  # tab_index -> modified
        self._file_paths: list[Path] = []  # 每个 tab 对应的文件路径
        # 中英文独立字体
        self._english_family = "Consolas"
        self._chinese_family = "Microsoft YaHei"
        self._font_size = 11
        self._font_bold = False
        self._font_italic = False
        self._load_editor_font()  # 从 ConfigManager 加载
        self._zoom_steps: dict[int, int] = {}  # tab_index -> zoom 步数

        self.setWindowTitle("配置文件编辑器")
        self.setFixedSize(1000, 700)
        self.setSizeGripEnabled(False)  # 隐藏右下角尺寸手柄

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        # 菜单栏
        self._menu_bar = QMenuBar()
        self._setup_menus()
        layout.addWidget(self._menu_bar)

        # 选项卡
        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tab_widget)

        # 加载配置文件
        self._load_files()

        # 状态栏（显示字体和缩放信息）
        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)  # 移除状态栏自带尺寸手柄
        self._update_status()
        layout.addWidget(self._status_bar)

        # 按钮栏
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(6, 6, 6, 6)
        btn_layout.addStretch()

        self.btn_save = QPushButton("保存 (Ctrl+S)")
        self.btn_save.clicked.connect(self.save_current)
        self.btn_save.setEnabled(len(self._file_paths) > 0)
        btn_layout.addWidget(self.btn_save)

        self.btn_save_all = QPushButton("全部保存")
        self.btn_save_all.clicked.connect(self.save_all)
        self.btn_save_all.setEnabled(len(self._file_paths) > 0)
        btn_layout.addWidget(self.btn_save_all)

        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self._on_close)
        btn_layout.addWidget(self.btn_close)

        layout.addLayout(btn_layout)

    def _load_files(self):
        """加载 Config 目录下所有 json 文件"""
        if not self._config_dir.exists():
            self._add_empty_tab("（Config 目录不存在）")
            return

        json_files = sorted(self._config_dir.glob("*.json"))
        # 排除程序自身的配置，避免误改
        json_files = [f for f in json_files if f.name != "config.json"]
        if not json_files:
            self._add_empty_tab("（Config 目录下没有 json 文件）")
            return

        for fp in json_files:
            self._add_file_tab(fp)

    def _add_file_tab(self, filepath: Path):
        """添加一个文件选项卡"""
        editor = ChineseTextEdit()
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        # 在任意位置截断，优先撑满整行到边缘再换行（适配长 JSON / URL）
        editor.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        # Tab 键宽度 = 4 个空格
        editor.setTabStopDistance(editor.fontMetrics().horizontalAdvance(' ') * 4)

        # 应用字体
        self._apply_font_to_editor(editor)

        # 安装事件过滤器以支持 Ctrl+滚轮缩放
        editor.installEventFilter(self)
        editor.setMouseTracking(True)

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            # 格式化 JSON（美化输出）
            try:
                parsed = json.loads(content)
                content = json.dumps(parsed, ensure_ascii=False, indent=4)
            except (json.JSONDecodeError, ValueError):
                pass  # 不是合法 JSON，保持原样
        except Exception:
            content = "// 无法读取文件"

        editor.setPlainText(content)

        # 跟踪修改状态
        idx = len(self._file_paths)
        self._file_paths.append(filepath)
        self._modified_flags[str(idx)] = False
        self._zoom_steps[idx] = 0
        editor.textChanged.connect(lambda i=idx: self._mark_modified(i))

        tab_name = filepath.name
        self.tab_widget.addTab(editor, tab_name)

    def _add_empty_tab(self, message: str):
        """添加提示选项卡"""
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(message)
        self.tab_widget.addTab(editor, "提示")

    def _mark_modified(self, idx: int):
        """标记选项卡已修改"""
        key = str(idx)
        was = self._modified_flags.get(key, False)
        if not was:
            self._modified_flags[key] = True
            self._update_tab_title(idx)

    def _update_tab_title(self, idx: int):
        """更新选项卡标题（未保存加 *）"""
        if idx < 0 or idx >= len(self._file_paths):
            return
        name = self._file_paths[idx].name
        if self._modified_flags.get(str(idx), False):
            name += " *"
        self.tab_widget.setTabText(idx, name)

    def _update_all_tab_titles(self):
        for i in range(min(len(self._file_paths), self.tab_widget.count())):
            self._update_tab_title(i)

    def _on_tab_changed(self, _index: int):
        """选项卡切换"""
        self._update_save_button_state()
        self._update_status()

    def _update_save_button_state(self):
        if not hasattr(self, 'btn_save'):
            return
        idx = self.tab_widget.currentIndex()
        if 0 <= idx < len(self._file_paths):
            self.btn_save.setEnabled(True)
        else:
            self.btn_save.setEnabled(False)

    # ──────────── 菜单 & 字体 ────────────

    def _setup_menus(self):
        """构建菜单栏"""
        # 查看菜单
        view_menu = self._menu_bar.addMenu("查看(&V)")

        self.action_line_numbers = QAction("显示行号(&L)", self)
        self.action_line_numbers.setCheckable(True)
        self.action_line_numbers.setChecked(True)
        self.action_line_numbers.triggered.connect(self._toggle_line_numbers)
        view_menu.addAction(self.action_line_numbers)

        view_menu.addSeparator()

        action_zoom_in = QAction("放大(&I)\tCtrl++", self)
        action_zoom_in.triggered.connect(self._zoom_in)
        view_menu.addAction(action_zoom_in)

        action_zoom_out = QAction("缩小(&O)\tCtrl+-", self)
        action_zoom_out.triggered.connect(self._zoom_out)
        view_menu.addAction(action_zoom_out)

        action_zoom_reset = QAction("恢复默认缩放\tCtrl+0", self)
        action_zoom_reset.triggered.connect(self._zoom_reset)
        view_menu.addAction(action_zoom_reset)
        
        # 格式菜单
        fmt_menu = self._menu_bar.addMenu("格式(&O)")
        action_font = QAction("字体(&F)...", self)
        action_font.triggered.connect(self._choose_font)
        fmt_menu.addAction(action_font)

    def _toggle_line_numbers(self):
        """切换行号显示"""
        visible = self.action_line_numbers.isChecked()
        for i in range(len(self._file_paths)):
            editor = self.tab_widget.widget(i)
            if isinstance(editor, ChineseTextEdit):
                editor.set_line_numbers_visible(visible)

    def _choose_font(self):
        """打开中英文字体统一设置对话框"""
        dlg = FontSettingsDialog(
            self._english_family, self._chinese_family,
            self._font_size, self._font_bold, self._font_italic,
            self
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._english_family = dlg.english_family
            self._chinese_family = dlg.chinese_family
            self._font_size = dlg.font_size
            self._font_bold = dlg.font_bold
            self._font_italic = dlg.font_italic
            self._apply_font_to_all()
            self._save_editor_font()

    def _build_font(self) -> QFont:
        """用中英文族名构建 QFont"""
        font = QFont()
        font.setFamilies([self._english_family, self._chinese_family])
        font.setPointSize(self._font_size)
        font.setBold(self._font_bold)
        font.setItalic(self._font_italic)
        return font

    def _apply_font_to_all(self):
        """将当前字体应用到所有编辑器选项卡"""
        f = self._build_font()
        for i in range(len(self._file_paths)):
            editor = self.tab_widget.widget(i)
            if isinstance(editor, QPlainTextEdit):
                self._zoom_steps[i] = 0
                editor.setFont(f)
                editor.setTabStopDistance(editor.fontMetrics().horizontalAdvance(' ') * 4)
        self._update_status()

    def _load_editor_font(self):
        """从 ConfigManager 加载编辑器字体配置"""
        try:
            fc = ConfigManager().config.editor_font
            if fc and isinstance(fc, dict):
                self._english_family = fc.get("english_family", self._english_family)
                self._chinese_family = fc.get("chinese_family", self._chinese_family)
                self._font_size = fc.get("size", self._font_size)
                self._font_bold = fc.get("bold", self._font_bold)
                self._font_italic = fc.get("italic", self._font_italic)
        except Exception:
            pass

    def _save_editor_font(self):
        """保存编辑器字体配置到 ConfigManager"""
        try:
            ConfigManager().update_editor_font(
                self._english_family, self._chinese_family,
                self._font_size, self._font_bold, self._font_italic
            )
            gui_log(f"编辑器字体已保存: EN={self._english_family}, CN={self._chinese_family}, {self._font_size}pt")
        except Exception as e:
            gui_log(f"保存编辑器字体失败: {e}", LogLevel.WARN)

    def _apply_font_to_editor(self, editor: QPlainTextEdit):
        """将当前字体应用到编辑器，可选重置缩放"""
        f = self._build_font()
        editor.setFont(f)
        editor.setTabStopDistance(editor.fontMetrics().horizontalAdvance(' ') * 4)

    # ──────────── 缩放 ────────────

    def _zoom_in(self):
        idx = self.tab_widget.currentIndex()
        if 0 <= idx < len(self._file_paths):
            editor = self.tab_widget.widget(idx)
            if isinstance(editor, QPlainTextEdit):
                editor.zoomIn(1)
                self._zoom_steps[idx] = self._zoom_steps.get(idx, 0) + 1
                self._update_status()

    def _zoom_out(self):
        idx = self.tab_widget.currentIndex()
        if 0 <= idx < len(self._file_paths):
            editor = self.tab_widget.widget(idx)
            if isinstance(editor, QPlainTextEdit):
                editor.zoomOut(1)
                self._zoom_steps[idx] = self._zoom_steps.get(idx, 0) - 1
                self._update_status()

    def _zoom_reset(self):
        idx = self.tab_widget.currentIndex()
        if 0 <= idx < len(self._file_paths):
            editor = self.tab_widget.widget(idx)
            if isinstance(editor, QPlainTextEdit):
                steps = self._zoom_steps.get(idx, 0)
                if steps > 0:
                    for _ in range(steps):
                        editor.zoomOut(1)
                elif steps < 0:
                    for _ in range(-steps):
                        editor.zoomIn(1)
                self._zoom_steps[idx] = 0
                self._update_status()

    def _zoom_percent(self, steps: int) -> int:
        """换算缩放步数 → 百分比"""
        return round(100 * (1.2 ** steps))

    # ──────────── 状态栏 ────────────

    def _update_status(self):
        """更新状态栏：中英文字体名、字号、缩放比例"""
        if not hasattr(self, '_status_bar'):
            return
        idx = self.tab_widget.currentIndex()
        steps = self._zoom_steps.get(idx, 0)
        pct = self._zoom_percent(steps)
        status = f"英文: {self._english_family}  |  中文: {self._chinese_family}  |  {self._font_size}pt"
        if steps != 0:
            status += f"  |  缩放: {pct}%"
        self._status_bar.showMessage(status)

    # ──────────── 事件过滤器（Ctrl+滚轮缩放）────────────

    def eventFilter(self, obj, event):
        if (isinstance(obj, QPlainTextEdit)
                and event.type() == QEvent.Type.Wheel
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            delta = event.angleDelta().y()
            if delta > 0:
                self._zoom_in()
            elif delta < 0:
                self._zoom_out()
            return True
        return super().eventFilter(obj, event)

    # ──────────── 键盘快捷键 ────────────

    def keyPressEvent(self, event):
        """Ctrl+S 保存 / Ctrl+=/-/0 缩放"""
        mod = Qt.KeyboardModifier.ControlModifier
        if event.modifiers() == mod:
            if event.key() == Qt.Key.Key_S:
                self.save_current()
                return
            elif event.key() in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
                self._zoom_in()
                return
            elif event.key() == Qt.Key.Key_Minus:
                self._zoom_out()
                return
            elif event.key() == Qt.Key.Key_0:
                self._zoom_reset()
                return
        super().keyPressEvent(event)

    def save_current(self):
        """保存当前选项卡"""
        idx = self.tab_widget.currentIndex()
        if idx < 0 or idx >= len(self._file_paths):
            return
        self._save_tab(idx)

    def save_all(self):
        """保存所有选项卡"""
        for idx in range(len(self._file_paths)):
            if self._modified_flags.get(str(idx), False):
                self._save_tab(idx)

    def _save_tab(self, idx: int):
        """保存指定选项卡"""
        filepath = self._file_paths[idx]
        editor = self.tab_widget.widget(idx)
        if not isinstance(editor, QPlainTextEdit):
            return

        content = editor.toPlainText()

        # JSON 格式化校验
        try:
            parsed = json.loads(content)
            content = json.dumps(parsed, ensure_ascii=False, indent=4)
            editor.setPlainText(content)
        except json.JSONDecodeError as e:
            # JSON 格式不合法，拒绝保存
            QMessageBox.critical(
                self, "JSON 格式错误",
                f"{filepath.name} 不是合法的 JSON 格式:\n\n{e}\n\n请修正后再保存。"
            )
            return

        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            self._modified_flags[str(idx)] = False
            self._update_tab_title(idx)
            self.file_saved.emit(str(filepath))
            gui_log(f"已保存: {filepath.name}")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"保存 {filepath.name} 失败:\n{e}")

    def _on_close(self):
        """关闭前检查未保存"""
        if any(self._modified_flags.values()):
            reply = QMessageBox.question(
                self, "未保存的更改",
                "有文件尚未保存，是否保存后关闭？",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Save:
                self.save_all()
            elif reply == QMessageBox.StandardButton.Cancel:
                return
        self.accept()
