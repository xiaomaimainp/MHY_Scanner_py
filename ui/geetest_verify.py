"""
极验(GeeTest)滑块验证模块
用于手机号登录时的滑块验证码

使用 PyQt6-WebEngine 加载验证页面，用户完成滑块后自动提取结果。
如果 PyQt6-WebEngine 未安装，将提示用户通过扫码登录。
"""

from __future__ import annotations

import json
import traceback
import urllib.parse
from typing import Optional, Tuple

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QMessageBox
from PyQt6.QtCore import Qt, QUrl
from core.logger import geetest_log, error, LogLevel

# 动态导入 WebEngine（可选依赖）
# 注意：改为在 verify_geetest() 中按需导入，以确保使用当前运行时的 Python 环境，
# 而不是 geetest_verify.py 被加载时的环境。


# GeeTest v3 验证页面 HTML 模板
# 即使 API 返回 use_v4=True，v3 的验证码也能正常工作
# challenge 可能为空（v4 API 不返回），此时用 gt 作为后备
GEETEST_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GeeTest</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            background: #fff;
            font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
        }
        #geetest-div {
            align-items: center;
        }
    </style>
</head>
<body>
    <div id="geetest-div"></div>

    <script src="https://static.geetest.com/static/js/gt.0.5.2.js"></script>
    <script>
        var gt = '__GT__';
        var challenge = '__CHALLENGE__';
        // v4 API 不返回 challenge，此时用 gt 作为后备
        if (!challenge || challenge.length === 0) {
            challenge = gt;
        }

        try {
            initGeetest({
                protocol: "https://",
                gt: gt,
                challenge: challenge,
                new_captcha: true,
                product: 'bind',
                api_server: 'api.geetest.com'
            }, function(captchaObj) {
                captchaObj.appendTo(document.getElementById('geetest-div'));

                captchaObj.onReady(function() {
                    captchaObj.verify();
                });

                captchaObj.onSuccess(function() {
                    var result = captchaObj.getValidate();
                    var data = encodeURIComponent(JSON.stringify(result));
                    setTimeout(function() {
                        window.location.href = 'geetest://result?data=' + data;
                    }, 500);
                });

                captchaObj.onError(function(err) {
                    console.error('GeeTest error:', err);
                });
            });
        } catch(e) {
            console.error('GeeTest init error:', e);
        }
    </script>
</body>
</html>
"""


class GeeTestVerifyDialog(QDialog):
    """
    极验滑块验证对话框 (支持 v3 / v4)
    
    Usage:
        dialog = GeeTestVerifyDialog(gt, challenge="", parent=parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.verification_result
            # result = {"geetest_challenge": "...", "geetest_validate": "...", "geetest_seccode": "..."}
    """
    
    def __init__(self, gt: str, challenge: str = "", parent=None):
        super().__init__(parent)
        self.gt = gt
        self.challenge = challenge  # v4 可能为空字符串
        self.verification_result: Optional[dict] = None
        self._webview = None  # QWebEngineView (imported in _init_ui)
        
        self.setWindowTitle("请完成验证")
        self.setFixedSize(400, 450)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        
        try:
            self._init_ui()
        except Exception as e:
            error(f"初始化UI失败: {e}\n{traceback.format_exc()}")
            raise
        
        self._load_captcha()
    
    def _init_ui(self):
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # 按需导入

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # WebEngine 视图（居中填满）
        self._webview = QWebEngineView()

        # 拦截 geetest:// URL scheme 导航
        page = self._webview.page()
        if page:
            profile = page.profile()
            if profile:
                profile.setHttpAcceptLanguage("zh-CN,zh;q=0.9")

        self._webview.urlChanged.connect(self._on_url_changed)
        self._webview.loadFinished.connect(self._on_load_finished)

        layout.addWidget(self._webview, 1)
        self.setLayout(layout)
    
    def _load_captcha(self):
        """加载验证页面"""
        html = GEETEST_HTML.replace("__GT__", self.gt).replace("__CHALLENGE__", self.challenge)
        self._webview.setHtml(html, QUrl("about:blank"))

    def _on_load_finished(self, ok: bool):
        if not ok:
            geetest_log("页面加载失败", LogLevel.ERROR)
    
    def _on_url_changed(self, url: QUrl):
        """拦截 geetest:// URL scheme 获取验证结果"""
        if url.scheme() == "geetest" and url.host() == "result":
            query = urllib.parse.parse_qs(url.query())
            data_str = query.get("data", [""])[0]
            if data_str:
                try:
                    result = json.loads(urllib.parse.unquote(data_str))
                    self.verification_result = result
                    self.accept()
                except (json.JSONDecodeError, Exception) as e:
                    error(f"解析极验结果失败: {e}\n{traceback.format_exc()}")
    
    def closeEvent(self, event):
        """关闭对话框时清理 webview"""
        if self._webview:
            self._webview.setUrl(QUrl("about:blank"))
        super().closeEvent(event)


def verify_geetest(gt: str, challenge: str = "", parent=None) -> Tuple[bool, Optional[dict]]:
    """
    执行极验滑块验证
    
    Args:
        gt: 极验 captchaId
        challenge: 极验 challenge（可为空）
        parent: 父窗口
    
    Returns:
        (success, result_dict)
        result_dict 包含 geetest_challenge, geetest_validate, geetest_seccode
    """
    # 按需导入 WebEngine（确保使用实际运行时的 Python 环境）
    try:
        import PyQt6.QtWebEngineWidgets as _webw  # noqa: F401
        import PyQt6.QtWebEngineCore as _webc      # noqa: F401
    except ImportError as _import_err:
        import sys
        _err_detail = str(_import_err)
        error(f"PyQt6-WebEngine 导入失败: {_err_detail}\n{traceback.format_exc()}")
        QMessageBox.warning(
            parent, "缺少组件",
            f"滑块验证需要 PyQt6-WebEngine 组件支持。\n\n"
            f"当前 Python: {sys.executable}\n\n"
            f"导入错误详情: {_err_detail}\n\n"
            f"常见原因:\n"
            f"1. pip install PyQt6-WebEngine 未在当前环境执行\n"
            f"2. 缺少 Visual C++ 运行时 (安装 vcredist)\n"
            f"3. QtWebEngineProcess.exe 文件损坏\n\n"
            f"请尝试重新安装:\n"
            f"pip uninstall PyQt6-WebEngine -y && pip install PyQt6-WebEngine\n\n"
            f"或使用「扫码登录」代替。"
        )
        return False, None
    
    try:
        dialog = GeeTestVerifyDialog(gt, challenge, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.verification_result
            if result:
                return True, result
    except Exception as e:
        error(f"验证对话框异常: {e}\n{traceback.format_exc()}")
        QMessageBox.warning(
            parent, "加载失败",
            f"安全验证加载失败，请重试或使用扫码登录。\n\n错误: {e}"
        )
    
    return False, None


def build_aigis_header(session_id: str, geetest_result: dict) -> str:
    """
    构建 X-Rpc-Aigis 请求头值（新版格式: session_id;base64_result）
    
    Args:
        session_id: 从 -3101 响应中获取的 session_id
        geetest_result: GeeTest 验证结果 (geetest_challenge, geetest_validate, geetest_seccode)
    
    Returns:
        字符串，如: '3b5b9887...;eyJjYXB0Y2hh...'
    """
    import base64 as _b64
    result_json = json.dumps(geetest_result, ensure_ascii=False)
    encoded = _b64.b64encode(result_json.encode()).decode()
    return f"{session_id};{encoded}"
