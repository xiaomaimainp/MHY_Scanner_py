"""
Cookie 刷新对话框
支持选择平台（抖音/B站），统一显示二维码扫码登录。
"""
import threading
import time as _time

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QProgressBar, QGroupBox, QStackedWidget, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QThread, QTimer, QUrl
from PyQt6.QtGui import QPixmap, QImage

from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings, QWebEnginePage

from core.logger import qr_log, bili_log, douyin_log, LogLevel


# ==================== 轮询 Worker ====================

class _BiliQRPollWorker(QObject):
    """B站二维码轮询后台线程"""
    status_changed = pyqtSignal(str)
    login_success = pyqtSignal(dict)
    login_failed = pyqtSignal(str)

    def __init__(self, qr_key: str, session, parent=None):
        super().__init__(parent)
        self.qr_key = qr_key
        self.session = session
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        import requests
        last_state = -1
        max_wait = 180
        started = _time.time()
        while self._running and _time.time() - started < max_wait:
            try:
                resp = self.session.get(
                    "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                    params={"qrcode_key": self.qr_key},
                    timeout=10,
                )
                poll = resp.json()
                code = poll.get("data", {}).get("code", poll.get("code", -1))

                if code == 0:
                    self.status_changed.emit("扫码确认成功，提取登录态...")
                    auth = {}
                    for ck, cv in self.session.cookies.items():
                        if ck in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                            if cv:
                                auth[ck] = cv
                    if auth.get("SESSDATA"):
                        bili_log(f"登录成功，获取到 Cookie: {list(auth.keys())}")
                        self.login_success.emit(auth)
                    else:
                        self.login_failed.emit("未获取到 SESSDATA")
                    return
                elif code == 86038:
                    self.login_failed.emit("二维码已过期，请重新获取")
                    return
                elif code == 86090 and last_state != 86090:
                    self.status_changed.emit("已扫码，请在手机上确认...")
                elif code == 86101 and last_state != 86101:
                    self.status_changed.emit("等待扫码...")

                last_state = code
            except Exception as e:
                self.status_changed.emit(f"轮询异常: {e}")
            _time.sleep(2)

        if self._running:
            self.login_failed.emit("登录超时（3分钟未确认）")


class _DouyinQRPollWorker(QObject):
    """抖音二维码轮询后台线程"""
    status_changed = pyqtSignal(str)
    login_success = pyqtSignal(dict)
    login_failed = pyqtSignal(str)

    def __init__(self, qr_token: str, csrf_token: str, session, parent=None):
        super().__init__(parent)
        self.qr_token = qr_token
        self.csrf_token = csrf_token
        self.session = session
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        import requests
        last_status = None
        max_wait = 300
        started = _time.time()
        while self._running and _time.time() - started < max_wait:
            try:
                resp = self.session.post(
                    "https://www.douyin.com/passport/qr/login/check_qrcode/",
                    data={
                        "csrf_token": self.csrf_token,
                        "token": self.qr_token,
                        "service": "https://www.douyin.com",
                    },
                    timeout=15,
                )
                poll = resp.json()
                status = str(poll.get("data", {}).get("status", ""))

                if status == "2":
                    self.status_changed.emit("扫码确认成功，提取登录态...")
                    auth = {}
                    key_fields = (
                        "sessionid", "sessionid_ss", "passport_csrf_token",
                        "sid_guard", "uid_tt", "sid_tt",
                        "odin_tt", "n_mh", "sid_ucp_v1", "ssid_ucp_v1",
                    )
                    for ck, cv in self.session.cookies.items():
                        if ck in key_fields and cv:
                            auth[ck] = cv
                    for ck, cv in self.session.cookies.items():
                        if ("session" in ck.lower() or "sid_" in ck.lower() or "uid" in ck.lower()) and ck not in auth:
                            if cv:
                                auth[ck] = cv
                    if auth.get("sessionid") or auth.get("sessionid_ss"):
                        douyin_log(f"登录成功，获取到 Cookie: {list(auth.keys())}")
                        self.login_success.emit(auth)
                    else:
                        self.login_failed.emit(f"未获取到关键Cookie，已获取: {list(self.session.cookies.keys())}")
                    return
                elif status == "1":
                    self.login_failed.emit("二维码已过期，请重新获取")
                    return
                elif status == "4" and last_status != "4":
                    self.status_changed.emit("已扫码，请在手机上确认...")
                elif status == "3" and last_status != "3":
                    self.status_changed.emit("等待扫码...")

                last_status = status
            except Exception as e:
                self.status_changed.emit(f"轮询异常: {e}")
            _time.sleep(2)

        if self._running:
            self.login_failed.emit("登录超时（5分钟未确认）")


# ==================== 主对话框 ====================

class CookieRefreshDialog(QDialog):
    """Cookie 刷新弹窗 —— 统一二维码扫码登录"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("刷新直播 Cookie")
        self.setMinimumSize(420, 480)
        self.resize(420, 500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._poll_thread: QThread | None = None
        self._poll_worker: _BiliQRPollWorker | _DouyinQRPollWorker | None = None
        self._session = None  # shared session for QR gen + poll
        self._qr_key = ""     # B站
        self._qr_token = ""   # 抖音
        self._csrf_token = "" # 抖音
        self._current_platform = 1  # 0=抖音, 1=B站

        # === 抖音 WebEngine 登录相关 ===
        self._web_view: QWebEngineView | None = None
        self._douyin_login_timer: QTimer | None = None
        self._douyin_cookies: dict[str, str] = {}  # 收集的抖音 cookie
        self._douyin_login_done = False
        self._douyin_login_started = 0.0  # 开始时间戳，用于超时检测

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)

        # ---- 平台选择 ----
        platform_layout = QHBoxLayout()
        platform_layout.addWidget(QLabel("直播平台:"))
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["抖音 (Douyin)", "B站 (BiliBili)"])
        self.platform_combo.currentIndexChanged.connect(self._on_platform_changed)
        platform_layout.addWidget(self.platform_combo)
        platform_layout.addStretch()
        layout.addLayout(platform_layout)

        # ---- 二维码区域（统一） ----
        self.qr_group = QGroupBox("二维码登录")
        qr_layout = QVBoxLayout()

        # 使用 QStackedWidget 切换 B站 QLabel / 抖音 QWebEngineView
        self._qr_stack = QStackedWidget()
        self._qr_stack.setMinimumSize(260, 260)

        # 第0页：B站 二维码 QLabel
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setStyleSheet("border: 1px solid #ccc; background: white;")
        self.qr_label.setText("点击 [刷新Cookie] 获取二维码\n扫码后系统自动检测登录")
        qr_page = QWidget()
        qr_page_layout = QVBoxLayout(qr_page)
        qr_page_layout.setContentsMargins(0, 0, 0, 0)
        qr_page_layout.addWidget(self.qr_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self._qr_stack.addWidget(qr_page)

        # 第1页：抖音 QWebEngineView（延迟创建）
        self._web_page_widget = QWidget()
        self._web_page_layout = QVBoxLayout(self._web_page_widget)
        self._web_page_layout.setContentsMargins(0, 0, 0, 0)
        self._qr_stack.addWidget(self._web_page_widget)

        self._qr_stack.setCurrentIndex(0)
        qr_layout.addWidget(self._qr_stack)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #666;")
        qr_layout.addWidget(self.status_label)

        self.qr_group.setLayout(qr_layout)
        layout.addWidget(self.qr_group)

        # ---- 进度条 ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 不确定进度
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        layout.addStretch()

        # ---- 按钮 ----
        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新Cookie")
        self.refresh_btn.clicked.connect(self._on_refresh)
        btn_layout.addWidget(self.refresh_btn)

        self.confirm_btn = QPushButton("确认")
        self.confirm_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.confirm_btn)
        layout.addLayout(btn_layout)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setEnabled(False)
        btn_layout.addWidget(self.cancel_btn)

        self.setLayout(layout)
        self._on_platform_changed(0)  # 默认抖音

    def _on_platform_changed(self, idx: int):
        self._current_platform = idx
        name = "抖音 (Douyin)" if idx == 0 else "B站 (BiliBili)"
        self.qr_group.setTitle(f"二维码登录 ({name})")
        self.cancel_btn.setEnabled(False)
        self._stop_polling()
        self._stop_douyin_web_login()
        self.refresh_btn.setEnabled(True)
        self.progress_bar.hide()
        # 切换显示：B站用 QLabel，抖音用 QWebEngineView
        if idx == 0:
            self._qr_stack.setCurrentIndex(1)
            self._web_page_widget.show()
        else:
            self._qr_stack.setCurrentIndex(0)
            self.qr_label.clear()
            self.qr_label.setText("点击 [刷新Cookie] 获取二维码\n扫码后系统自动检测登录")
        self.status_label.setText("")
        self.status_label.setStyleSheet("color: #666;")

    def _on_refresh(self):
        self._current_platform = self.platform_combo.currentIndex()
        if self._current_platform == 0:
            douyin_log("开始刷新抖音 Cookie")
        else:
            bili_log("开始刷新B站 Cookie")
        if self._current_platform == 0:
            self._do_douyin_refresh()
        else:
            self._do_bilibili_refresh()

    # ==================== 抖音 WebEngine 二维码刷新 ====================
    def _do_douyin_refresh(self):
        self.refresh_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.show()
        self.status_label.setText("正在打开抖音登录页面...")
        self.status_label.setStyleSheet("color: #1976D2;")
        self._douyin_login_done = False
        self._douyin_cookies.clear()
        self._douyin_login_started = _time.time()
        douyin_log("开始刷新抖音 Cookie（WebEngine 浏览器模式）")

        # 初始化 WebEngine（如果尚未初始化）
        self._setup_douyin_web_view()

        # 加载抖音登录页面（真浏览器，无需担心 anti-bot）
        self._web_view.load(QUrl("https://www.douyin.com/passport/login/"))

        # 启动定时器检测登录成功（每 1.5 秒检查 cookie）
        if self._douyin_login_timer is None:
            self._douyin_login_timer = QTimer(self)
            self._douyin_login_timer.timeout.connect(self._check_douyin_web_login)
        self._douyin_login_timer.start(1500)

    def _setup_douyin_web_view(self):
        """初始化一次性的 QWebEngineView"""
        if self._web_view is not None:
            return
        # --- 伪装成正常 Chrome 浏览器，避免被抖音识别为非法应用 ---
        # 使用独立 profile，避免污染默认 profile 的 cookie / 设置
        profile = QWebEngineProfile("douyin_login", self)
        # 关键：User-Agent 去掉 QtWebEngine 标识，用标准 Chrome UA
        profile.setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
        profile.setHttpAcceptLanguage("zh-CN,zh;q=0.9,en;q=0.8")
        # 关闭可能暴露自动化特征的设置
        settings = profile.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        # 允许跨域和插件以避免触发反爬检测
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.HyperlinkAuditingEnabled, False)

        self._web_view = QWebEngineView()
        # 用自定义 profile 创建页面，替换默认页面
        page = QWebEnginePage(profile, self._web_view)
        self._web_view.setPage(page)
        self._web_view.setMinimumSize(260, 260)
        self._web_page_layout.addWidget(self._web_view)

        # 监控 cookie 变化，收集所有 douyin 相关 cookie
        store = profile.cookieStore()
        store.cookieAdded.connect(self._on_douyin_web_cookie_added)

        # 监控页面加载
        self._web_view.loadFinished.connect(self._on_douyin_web_load_finished)

    def _on_douyin_web_cookie_added(self, cookie):
        """收集 WebEngine 浏览器中设置的所有 cookie"""
        try:
            name = bytes(cookie.name()).decode("utf-8", errors="replace")
            value = bytes(cookie.value()).decode("utf-8", errors="replace")
            self._douyin_cookies[name] = value
        except Exception:
            pass

    def _on_douyin_web_load_finished(self, ok: bool):
        if not ok:
            douyin_log("抖音登录页面加载失败", level=LogLevel.ERROR)
            self.status_label.setText("页面加载失败，尝试游客Cookie...")
            self.status_label.setStyleSheet("color: #F57C00;")
            self._stop_douyin_web_login()
            self._do_tourist_fallback()
            return
        # 检查页面内容是否返回了反爬错误 JSON
        try:
            self._web_view.page().runJavaScript(
                "document.body.innerText",
                self._on_douyin_page_content
            )
        except Exception:
            pass

    def _on_douyin_page_content(self, text: str):
        """检查页面内容是否包含反爬/非法应用错误"""
        if not text:
            self._check_douyin_web_login()
            return
        text = text.strip()
        # 如果返回了 JSON 错误（如 error_code: 22 非法应用）
        if text.startswith("{") and ("error_code" in text or "非法应用" in text):
            self.status_label.setText("抖音拒绝了浏览器访问（非法应用检测），尝试游客Cookie...")
            self.status_label.setStyleSheet("color: #F57C00;")
            douyin_log(f"抖音登录页面返回错误: {text[:200]}", level=LogLevel.ERROR)
            self._stop_douyin_web_login()
            self._do_tourist_fallback()
            return
        # 页面正常，开始检测登录
        self._check_douyin_web_login()

    def _check_douyin_web_login(self):
        """定时检查是否已登录成功（sessionid / sessionid_ss 出现）"""
        if self._douyin_login_done:
            return

        # 5 分钟超时，兜底游客 Cookie
        if _time.time() - self._douyin_login_started > 300:
            douyin_log("网页扫码登录超时（5分钟），尝试游客Cookie兜底", level=LogLevel.WARN)
            self._stop_douyin_web_login()
            self._do_tourist_fallback()
            return

        has_session = (
            "sessionid" in self._douyin_cookies
            or "sessionid_ss" in self._douyin_cookies
        )

        if has_session:
            self._on_douyin_web_login_success()
        else:
            # 还没登录，更新状态提示
            current_url = self._web_view.url().toString() if self._web_view else ""
            if "passport/login" in current_url:
                self.status_label.setText("请使用 抖音APP 扫描页面中的二维码")
                self.status_label.setStyleSheet("color: #1976D2;")
                self.progress_bar.hide()
            elif self.status_label.text() == "正在打开抖音登录页面...":
                self.status_label.setText("请使用 抖音APP 扫描页面中的二维码")
                self.status_label.setStyleSheet("color: #1976D2;")
                self.progress_bar.hide()

    def _on_douyin_web_login_success(self):
        """抖音 WebEngine 登录成功，提取并保存 Cookie"""
        self._douyin_login_done = True
        if self._douyin_login_timer:
            self._douyin_login_timer.stop()
        self._stop_polling()

        # 提取关键 Cookie 字段
        key_fields = (
            "sessionid", "sessionid_ss", "passport_csrf_token",
            "sid_guard", "uid_tt", "sid_tt",
            "odin_tt", "n_mh", "sid_ucp_v1", "ssid_ucp_v1",
        )
        auth = {}
        for k, v in self._douyin_cookies.items():
            if k in key_fields and v:
                auth[k] = v
        # 也收集其他可能遗漏的 session 相关 cookie
        for k, v in self._douyin_cookies.items():
            if ("session" in k.lower() or "sid_" in k.lower() or "uid" in k.lower()) and k not in auth:
                if v:
                    auth[k] = v

        if auth.get("sessionid") or auth.get("sessionid_ss"):
            douyin_log(f"登录成功，获取到 Cookie: {list(auth.keys())}")
        else:
            douyin_log(f"检测到登录但未获取到 sessionid，已有 cookie: {list(self._douyin_cookies.keys())}", level=LogLevel.WARN)

        cookie_str = "; ".join(f"{k}={v}" for k, v in auth.items())
        self.cancel_btn.setEnabled(False)
        try:
            from core.config import ConfigManager
            ConfigManager().update_douyin_cookie(cookie_str)
            msg = f"抖音登录成功！({', '.join(auth.keys())} 已保存)"
            self.status_label.setText(msg)
            self.status_label.setStyleSheet("color: #388E3C; font-weight: bold;")
            douyin_log(msg)
        except Exception as e:
            msg = f"登录成功但保存失败: {e}"
            self.status_label.setText(msg)
            self.status_label.setStyleSheet("color: #F57C00;")
            douyin_log(msg, level=LogLevel.WARN)

    def _stop_douyin_web_login(self):
        """停止 WebEngine 登录检测"""
        if self._douyin_login_timer:
            self._douyin_login_timer.stop()
        self._douyin_login_done = False
        self._douyin_cookies.clear()
        if self._web_view:
            self._web_view.stop()

    def _do_tourist_fallback(self):
        """二维码无法获取时的游客 Cookie 兜底"""
        self.cancel_btn.setEnabled(False)
        self.progress_bar.hide()
        try:
            from scanner.livestream import LiveDouyin
            cookie = LiveDouyin._get_cookie()
            if cookie:
                msg = f"游客Cookie刷新成功！（已保存 {len(cookie)} 字符）"
                self.status_label.setText(msg)
                self.status_label.setStyleSheet("color: #388E3C; font-weight: bold;")
                self.qr_label.setText("（未获取二维码，使用游客Cookie）")
                douyin_log(msg)
            else:
                msg = "Cookie 刷新失败（网络异常）"
                self.status_label.setText(msg)
                self.status_label.setStyleSheet("color: #D32F2F;")
                self.qr_label.setText("刷新失败")
                douyin_log(msg, level=LogLevel.ERROR)
        except Exception as e:
            msg = f"Cookie 刷新失败: {e}"
            self.status_label.setText(msg)
            self.status_label.setStyleSheet("color: #D32F2F;")
            self.qr_label.setText("刷新失败")
            douyin_log(msg, level=LogLevel.ERROR)
        self.refresh_btn.setEnabled(True)

    # ==================== B站二维码刷新 ====================
    def _do_bilibili_refresh(self):
        self.refresh_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.show()
        self.status_label.setText("正在生成二维码...")
        self.status_label.setStyleSheet("color: #1976D2;")
        self.qr_label.clear()
        self.qr_label.setText("正在生成...")

        def _run():
            import requests

            self._stop_polling()

            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            })

            try:
                resp = self._session.get(
                    "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
                    timeout=10,
                )
                data = resp.json()
                if data.get("code") != 0:
                    msg = f"生成二维码失败: {data.get('message', '未知错误')}"
                    self.status_label.setText(msg)
                    self.status_label.setStyleSheet("color: #D32F2F;")
                    bili_log(msg, level=LogLevel.ERROR)
                    self.refresh_btn.setEnabled(True)
                    self.cancel_btn.setEnabled(False)
                    self.progress_bar.hide()
                    return

                self._qr_key = data["data"]["qrcode_key"]
                qr_url = data["data"]["url"]

                self._show_qr_image(qr_url)
                self.status_label.setText("请使用 B站APP 扫描二维码")
                self.status_label.setStyleSheet("color: #1976D2;")
                bili_log("请使用 B站APP 扫描二维码")
                self.progress_bar.hide()
                self.refresh_btn.setEnabled(True)
                
                self._start_bili_polling()

            except Exception as e:
                self.status_label.setText(f"获取二维码失败: {e}")
                self.status_label.setStyleSheet("color: #D32F2F;")
                bili_log(f"获取二维码失败: {e}", level=LogLevel.ERROR)
                self.refresh_btn.setEnabled(True)
                self.cancel_btn.setEnabled(False)
                self.progress_bar.hide()

        threading.Thread(target=_run, daemon=True).start()

    # ==================== QR 图片显示 ====================
    def _show_qr_image(self, url: str):
        """在线程中生成二维码图片并显示"""
        try:
            import qrcode
            from io import BytesIO
            qr = qrcode.QRCode(border=2, box_size=8)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            buf = BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)

            qimg = QImage()
            qimg.loadFromData(buf.read())
            pixmap = QPixmap.fromImage(qimg)
            pixmap = pixmap.scaled(220, 220, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.qr_label.setPixmap(pixmap)
        except ImportError:
            from PyQt6.QtGui import QPainter, QFont, QPen
            pm = QPixmap(280, 280)
            pm.fill(Qt.GlobalColor.white)
            painter = QPainter(pm)
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.setFont(QFont("Microsoft YaHei", 9))
            text_lines = [
                "请安装 qrcode 库显示二维码:",
                "pip install qrcode[pil]",
                "",
                "或打开以下链接:",
            ]
            y = 50
            for line in text_lines:
                rect = painter.boundingRect(0, 0, 280, 20, Qt.AlignmentFlag.AlignCenter, line)
                x = (280 - rect.width()) // 2
                painter.drawText(x, y, line)
                y += 25
            painter.end()
            self.qr_label.setPixmap(pm)
            self.status_label.setText(f"二维码链接: {url[:60]}...")
            self.status_label.setStyleSheet("color: #F57C00;")

    # ==================== 轮询控制 ====================
    def _start_bili_polling(self):
        self._poll_thread = QThread(self)
        self._poll_worker = _BiliQRPollWorker(self._qr_key, self._session)
        self._poll_worker.moveToThread(self._poll_thread)

        self._poll_worker.status_changed.connect(self._on_poll_status)
        self._poll_worker.login_success.connect(self._on_bili_login_success)
        self._poll_worker.login_failed.connect(self._on_bili_login_failed)

        self._poll_thread.started.connect(self._poll_worker.run)
        self._poll_thread.start()

    def _start_douyin_polling(self):
        self._poll_thread = QThread(self)
        self._poll_worker = _DouyinQRPollWorker(self._qr_token, self._csrf_token, self._session)
        self._poll_worker.moveToThread(self._poll_thread)

        self._poll_worker.status_changed.connect(self._on_poll_status)
        self._poll_worker.login_success.connect(self._on_douyin_login_success)
        self._poll_worker.login_failed.connect(self._on_douyin_login_failed)

        self._poll_thread.started.connect(self._poll_worker.run)
        self._poll_thread.start()

    def _stop_polling(self):
        if self._poll_worker:
            self._poll_worker.stop()
        if self._poll_thread and self._poll_thread.isRunning():
            self._poll_thread.quit()
            self._poll_thread.wait(2000)

    def _on_poll_status(self, msg: str):
        self.status_label.setText(msg)
        self.status_label.setStyleSheet("color: #1976D2;")
        qr_log(msg)

    # ==================== B站结果处理 ====================
    def _on_bili_login_success(self, auth: dict):
        self._stop_polling()
        self.cancel_btn.setEnabled(False)
        cookie_str = "; ".join(f"{k}={v}" for k, v in auth.items())
        try:
            from core.config import ConfigManager
            ConfigManager().update_bilibili_cookie(cookie_str)
            msg = f"B站登录成功！({', '.join(auth.keys())} 已保存)"
            self.status_label.setText(msg)
            self.status_label.setStyleSheet("color: #388E3C; font-weight: bold;")
            bili_log(msg)
        except Exception as e:
            msg = f"登录成功但保存失败: {e}"
            self.status_label.setText(msg)
            self.status_label.setStyleSheet("color: #F57C00;")
            bili_log(msg, level=LogLevel.WARN)

    def _on_bili_login_failed(self, reason: str):
        self._stop_polling()
        self.cancel_btn.setEnabled(False)
        msg = f"登录失败: {reason}"
        self.status_label.setText(msg)
        self.status_label.setStyleSheet("color: #D32F2F;")
        bili_log(msg, level=LogLevel.ERROR)

    # ==================== 抖音结果处理 ====================
    def _on_douyin_login_success(self, auth: dict):
        self._stop_polling()
        self.cancel_btn.setEnabled(False)
        cookie_str = "; ".join(f"{k}={v}" for k, v in auth.items())
        try:
            from core.config import ConfigManager
            ConfigManager().update_douyin_cookie(cookie_str)
            msg = f"抖音登录成功！({', '.join(auth.keys())} 已保存)"
            self.status_label.setText(msg)
            self.status_label.setStyleSheet("color: #388E3C; font-weight: bold;")
            douyin_log(msg)
        except Exception as e:
            msg = f"登录成功但保存失败: {e}"
            self.status_label.setText(msg)
            self.status_label.setStyleSheet("color: #F57C00;")
            douyin_log(msg, level=LogLevel.WARN)

    def _on_douyin_login_failed(self, reason: str):
        self._stop_polling()
        self.cancel_btn.setEnabled(False)
        msg = f"登录失败: {reason}"
        self.status_label.setText(msg)
        self.status_label.setStyleSheet("color: #D32F2F;")
        douyin_log(msg, level=LogLevel.ERROR)

    # ==================== 取消 & 关闭 ====================
    def _on_cancel(self):
        """取消当前操作"""
        self._stop_polling()
        self._stop_douyin_web_login()
        self.cancel_btn.setEnabled(False)
        self.refresh_btn.setEnabled(True)
        self.progress_bar.hide()
        msg = "已取消，点击 [刷新Cookie] 重新获取"
        self.status_label.setText(msg)
        self.status_label.setStyleSheet("color: #666;")
        if self._current_platform == 0:
            douyin_log(f"已取消刷新操作")
        else:
            bili_log(f"已取消刷新操作")
        self.qr_label.clear()
        self.qr_label.setText("点击 [刷新Cookie] 获取二维码\n扫码后系统自动检测登录")

    def closeEvent(self, event):
        self._stop_polling()
        self._stop_douyin_web_login()
        super().closeEvent(event)
