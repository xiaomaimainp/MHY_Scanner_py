"""
极验(GeeTest)滑块验证模块
用于手机号登录时的滑块验证码

对齐 C++ 编译版 WindowGeeTest（WebView2）的实现：
- v4 使用 https://static.geetest.com/v4/gt4.js + initGeetest4，
  product='popup'，必须带服务端下发的 riskType，否则 SDK 静默渲染失败（窗口空白）。
- v3 使用 fullpage.9.1.9.js + initGeetest。
结果通过导航到 geetest://result 回传（QtWebEngine 无 window.chrome.webview）。
如果 PyQt6-WebEngine 未安装，将提示用户通过扫码登录。
"""

from __future__ import annotations

import json
import os
import traceback
import urllib.parse
from typing import Optional, Tuple

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QMessageBox
from PyQt6.QtCore import Qt, QUrl
from core.logger import geetest_log, error, LogLevel


def _log(msg: str, level: int = LogLevel.INFO):
    """安全日志：日志组件异常绝不应中断/崩溃验证流程

    曾出现 Logger 缺少 geetest 方法导致 geetest_log 抛 AttributeError，
    而 except 分支里再打日志又触发同样的异常，形成级联崩溃并直接打断登录流程。
    这里统一吞掉日志异常，保证验证码流程不受日志组件状态影响。
    """
    try:
        geetest_log(msg, level)
    except Exception:
        pass


# 动态导入 WebEngine（可选依赖）
# 注意：改为在 verify_geetest() 中按需导入，以确保使用当前运行时的 Python 环境，
# 而不是 geetest_verify.py 被加载时的环境。


# GeeTest 验证页面模板（对齐 C++ WindowGeeTest.cpp 的 Script 常量）
# 占位符：__SCRIPT__ = 脚本地址；__V4__ = true/false；__CONFIG__ = 配置 JSON
GEETEST_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  html, body { margin: 0; padding: 0; background: #f5f6f8; }
  #captcha { display: flex; align-items: center; justify-content: center; min-height: 100vh; }
</style>
</head>
<body>
<div id="captcha"></div>
<script src="__SCRIPT__" async defer></script>
<script>
  var __env = __V4__;
  var __config = __CONFIG__;
  var __done = false;
  var __tries = 0;
  var __fallback = false;   // 是否已从 bind 回退到 popup 模式
  function __send(event, data) {
    var payload = encodeURIComponent(JSON.stringify(data || {}));
    try { window.location.href = 'geetest://result?event=' + event + '&data=' + payload; } catch (e) {}
  }
  function __geetest() {
    var mount = document.getElementById('captcha');
    if (__env) {
    if (!window.initGeetest && !window.initGeetest4) {
      __send('failed', { message: '验证脚本不可用，请重试' });
      return;
    }
      // 对齐 ErYou WindowGeeTest.cpp:106-130 的 v4 配置：
      //   product='bind' + language='zho' + hideSuccess=true + userInfo={"session_id":...}
      // userInfo 把极验凭证与米游社 aigis 会话绑定，缺失会回 -3102「图片验证码失败」。
      // bind 模式必须显式 showCaptcha()（第130行）才会弹面板；此处再加看门狗：
      // 若 bind 在 QtWebEngine 下 2.5s 内没渲染出任何可见元素，自动回退 popup+nativeButton
      // （该组合已实测可渲染、可滑动），确保窗口不空白。
      function __visibleCount() {
        var els = document.querySelectorAll('[class*="geetest"]');
        var n = 0;
        for (var i = 0; i < els.length; i++) {
          var r = els[i].getBoundingClientRect();
          if (r.width > 0 && r.height > 0) n++;
        }
        return n;
      }
      function __startV4(bind) {
        var cfg = {
          captchaId: __config.gt,
          language: 'zho',
          hideSuccess: true,
          riskType: __config.risk_type,
          userInfo: __config.userInfo || ''
        };
        if (bind) cfg.product = 'bind';
        else { cfg.product = 'popup'; cfg.nativeButton = { width: '100%', borderRadius: '4px' }; }
        window.initGeetest4(cfg, function (captcha) {
          console.log('[geetest] initGeetest4 callback mode=' + (bind ? 'bind' : 'popup'));
          captcha.appendTo('#captcha', function () {});
          captcha.onReady(function () {
            console.log('[geetest] ready mode=' + (bind ? 'bind' : 'popup'));
            if (bind) {
              try { captcha.showCaptcha(); } catch (e) { console.error('[geetest] showCaptcha 失败', e); }
            }
            if (bind && !__fallback) {
              setTimeout(function () {
                if (__done || __fallback) return;
                if (__visibleCount() === 0) {
                  __fallback = true;
                  console.error('[geetest] bind 未渲染出可见元素，自动回退 popup 模式');
                  var box = document.getElementById('captcha');
                  if (box) box.innerHTML = '';
                  __startV4(false);
                }
              }, 2500);
            }
          });
          captcha.onSuccess(function () {
            if (__done) return; __done = true;
            __send('success', captcha.getValidate());
          });
          captcha.onError(function (e) { console.error('[geetest] error', e); __send('failed', { message: '极验验证失败，请重试' }); });
          captcha.onClose(function () { __send('closed', {}); });
        });
      }
      __startV4(true);
    } else {
      if (typeof window.initGeetest !== 'function') {
        console.error('[geetest] initGeetest 未就绪');
        __send('failed', { message: '验证脚本未加载(v3)，请检查网络后重试' });
        return;
      }
      window.initGeetest(__config, function (captcha) {
        console.log('[geetest] initGeetest callback');
        captcha.appendTo('#captcha');
        captcha.onReady(function () {});
        captcha.onSuccess(function () {
          if (__done) return; __done = true;
          __send('success', captcha.getValidate());
        });
        captcha.onError(function (e) { __send('failed', { message: '极验验证失败，请重试' }); });
        captcha.onClose(function () { __send('closed', {}); });
      });
    }
  }
  function __wait() {
    // async defer 脚本不阻塞 DOMContentLoaded，直接跑会拿不到 initGeetest4/1
    // （导致静默走 failed、窗口空白）。这里轮询等脚本就绪，超时 10 秒。
    if (window.initGeetest4 || window.initGeetest) { __geetest(); return; }
    if (__tries++ > 100) { __send('failed', { message: '验证脚本加载超时，请检查网络后重试' }); return; }
    setTimeout(__wait, 100);
  }
  if (document.readyState === 'complete' || document.readyState === 'interactive') __wait();
  else window.addEventListener('DOMContentLoaded', __wait);
</script>
</body>
</html>
"""


class GeeTestVerifyDialog(QDialog):
    """
    极验滑块验证对话框 (支持 v3 / v4)

    Usage:
        dialog = GeeTestVerifyDialog(gt, challenge="", parent=parent,
                                     use_v4=True, risk_type="...")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.verification_result
            # result 为 captcha.getValidate() 返回的字典
    """

    def __init__(self, gt: str, challenge: str = "", parent=None,
                 use_v4: bool = False, risk_type: str = "", session_id: str = ""):
        super().__init__(parent)
        self.gt = gt
        self.challenge = challenge  # v3 使用；v4 忽略
        self.use_v4 = use_v4
        self.risk_type = risk_type  # v4 必填，来自服务端下发
        # v4 必填：米游社 aigis 会话 id。需经 userInfo 传给极验，
        # 用于将验证凭证与该会话绑定，否则服务端回 -3102「图片验证码失败」。
        self.session_id = session_id
        self.verification_result: Optional[dict] = None
        self._webview = None  # QWebEngineView (imported in _init_ui)

        self.setWindowTitle("请完成验证")
        self.setFixedSize(400, 480)
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

        class _ConsolePage(QWebEnginePage):
            """转发 JS console 到项目日志，便于定位验证页空白原因"""

            def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
                try:
                    _log(f"[js] {message} (line {line})", LogLevel.DEBUG)
                except Exception:
                    pass

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)

        self._status = QLabel("正在加载验证…", self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        # WebEngine 视图（居中填满）
        self._webview = QWebEngineView()

        page = self._webview.page()
        if page:
            profile = page.profile()
            if profile:
                profile.setHttpAcceptLanguage("zh-CN,zh;q=0.9")
            try:
                page.renderProcessTerminated.connect(self._on_render_terminated)
            except Exception:
                pass

        self._webview.urlChanged.connect(self._on_url_changed)
        self._webview.loadFinished.connect(self._on_load_finished)

        layout.addWidget(self._webview, 1)
        self.setLayout(layout)

    def _load_captcha(self):
        """加载验证页面（对齐 C++ WindowGeeTest::Init）

        配置：v4 仅需 gt + risk_type；v3 需 gt + challenge 等。
        以 https 源加载，保证极验 SDK 拿到有效安全上下文（Origin）。
        """
        if self._webview is None:
            _log("WebEngine 视图未初始化，无法加载验证页", LogLevel.ERROR)
            return

        config: dict = {"gt": self.gt}
        if self.use_v4:
            config["risk_type"] = self.risk_type
            # 对齐 C++ WindowGeeTest::Init：userInfo 是 JSON 字符串，内含 session_id
            config["userInfo"] = json.dumps({"session_id": self.session_id},
                                            ensure_ascii=False)
        else:
            config["challenge"] = self.challenge
            config["new_captcha"] = True
            config["offline"] = False
            config["product"] = "popup"
            config["width"] = "100%"

        config_json = json.dumps(config, ensure_ascii=False).replace("<", "\\u003c")
        # v4 必须是 /v4/gt4.js（实测 /static/js/gt4.js 为 404，会导致 SDK 加载失败、窗口空白）；
        # 该地址来自 ErYou 2.0.2 编译版实装，已验证返回 200。
        script = ("https://static.geetest.com/v4/gt4.js"
                  if self.use_v4
                  else "https://static.geetest.com/static/js/fullpage.9.1.9.js")

        html = (GEETEST_HTML
                .replace("__SCRIPT__", script)
                .replace("__V4__", "true" if self.use_v4 else "false")
                .replace("__CONFIG__", config_json))

        _log(f"加载极验页面: use_v4={self.use_v4}, script={script}", LogLevel.DEBUG)
        self._webview.setHtml(html, QUrl("https://geetest.localhost/"))

    def _on_load_finished(self, ok: bool):
        if ok:
            self._status.setText("请在弹出的验证框中完成人机验证")
        else:
            # 拦截 geetest:// 导航（acceptNavigationRequest 返回 False）会触发
            # loadFinished(False)，这是正常流程而非加载失败，不应报错误导排查。
            if getattr(self, "_geetest_handled", False):
                return
            self._status.setText("验证页面加载失败，请重试或使用扫码登录")
            _log("页面加载失败", LogLevel.ERROR)

    def _probe(self, when: str):
        """探测验证页内部状态：脚本是否加载、滑块容器是否被填充"""
        if not getattr(self, "_webview", None):
            return
        js = (
            "(function(){try{"
            "var c=document.getElementById('captcha');"
            # vis: 可见极验元素数量。bind 模式面板可能不在 #captcha 内，
            # 只看 capLen 会误判为“未渲染”（曾据此得出错误结论），故一并统计可见元素。
            "var els=document.querySelectorAll('[class*=geetest]');var v=0;"
            "for(var i=0;i<els.length;i++){var r=els[i].getBoundingClientRect();"
            "if(r.width>0&&r.height>0)v++;}"
            "return JSON.stringify({has4:typeof window.initGeetest4,"
            "has3:typeof window.initGeetest,"
            "capLen:(c?c.innerHTML.length:-1),vis:v,"
            "url:location.href,ref:document.referrer||''});"
            "}catch(e){return 'ERR:'+e;}})()"
        )
        try:
            page = self._webview.page()
            if page is None:
                return
            page.runJavaScript(
                js, lambda r, _w=when: _log(f"[probe {_w}] {r}", LogLevel.INFO))
        except Exception as e:
            _log(f"[probe {when}] 执行失败: {e}", LogLevel.WARN)

    def _on_render_terminated(self, status, exit_code):
        _log(f"WebEngine 渲染进程终止: status={status}, exit={exit_code}", LogLevel.ERROR)
        self._status.setText("验证组件崩溃，请重试或使用扫码登录")

    def _on_url_changed(self, url: QUrl):
        """拦截 geetest:// URL scheme，获取验证结果或失败/关闭事件"""
        if url.scheme() != "geetest" or url.host() != "result":
            return
        query = urllib.parse.parse_qs(url.query())
        event = (query.get("event", [""])[0] or "").strip()
        data_str = query.get("data", [""])[0]

        if event == "success":
            try:
                result = json.loads(data_str) if data_str else {}
            except Exception as e:
                error(f"解析极验结果失败: {e}\n{traceback.format_exc()}")
                self.reject()
                return
            self.verification_result = result
            self.accept()
        elif event == "failed":
            _log("极验验证失败", LogLevel.WARN)
            self.reject()
        elif event == "closed":
            _log("极验验证已关闭", LogLevel.INFO)
            self.reject()

    def closeEvent(self, event):
        """关闭对话框时清理 webview"""
        if self._webview:
            self._webview.setUrl(QUrl("about:blank"))
        super().closeEvent(event)


def verify_geetest(gt: str, challenge: str = "", parent=None,
                   use_v4: bool = False, risk_type: str = "",
                   session_id: str = "") -> Tuple[bool, Optional[dict]]:
    """
    执行极验滑块验证

    Args:
        gt: 极验 captchaId
        challenge: 极验 challenge（v3 使用，v4 可为空）
        parent: 父窗口
        use_v4: 是否使用 GeeTest v4（米游社短信登录现为 v4）
        risk_type: v4 风险类型，来自服务端 -3101 响应的 risk_type

    Returns:
        (success, result_dict)
        result_dict 为 captcha.getValidate() 返回的字典
    """
    # 让 WebEngine 继承系统/环境变量代理（ErYou 的 WebView2 默认使用系统网络栈；
    # QWebEngine 可能未继承，导致极验后端主机连不通而报“网络错误”）
    try:
        from PyQt6.QtNetwork import QNetworkProxy
        _proxy_url = (os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
                      or os.environ.get("https_proxy") or os.environ.get("http_proxy"))
        if _proxy_url:
            _p = urllib.parse.urlparse(_proxy_url)
            _proxy = QNetworkProxy(QNetworkProxy.ProxyType.HttpProxy,
                                   _p.hostname or "127.0.0.1", int(_p.port or 8080))
            if _p.username:
                _proxy.setUser(_p.username)
            if _p.password:
                _proxy.setPassword(_p.password)
            QNetworkProxy.setApplicationProxy(_proxy)
            _log(f"WebEngine 使用代理: {_p.hostname}:{_p.port}", LogLevel.INFO)
        else:
            # 无环境变量代理：显式读取系统代理（QNetworkProxy 没有 SystemProxy 枚举，
            # 正确做法是用 QNetworkProxyFactory.systemProxyForQuery）
            try:
                from PyQt6.QtNetwork import QNetworkProxyFactory, QNetworkProxyQuery
                _proxies = QNetworkProxyFactory.systemProxyForQuery(
                    QNetworkProxyQuery(QUrl("https://api.geetest.com")))
                if _proxies:
                    QNetworkProxy.setApplicationProxy(_proxies[0])
                    _log("WebEngine 使用系统代理", LogLevel.INFO)
                else:
                    _log("系统未配置代理，使用默认直连", LogLevel.INFO)
            except Exception as _sys_e:
                _log(f"读取系统代理失败，使用默认直连: {_sys_e}", LogLevel.INFO)
    except Exception as _e:
        _log(f"设置 WebEngine 代理失败: {_e}", LogLevel.WARN)

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
        dialog = GeeTestVerifyDialog(gt, challenge, parent,
                                     use_v4=use_v4, risk_type=risk_type,
                                     session_id=session_id)
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
        geetest_result: GeeTest 验证结果（captcha.getValidate() 的返回值）

    Returns:
        字符串，如: '3b5b9887...;eyJjYXB0Y2hh...'
    """
    import base64 as _b64
    result_json = json.dumps(geetest_result, ensure_ascii=False)
    encoded = _b64.b64encode(result_json.encode()).decode()
    return f"{session_id};{encoded}"
