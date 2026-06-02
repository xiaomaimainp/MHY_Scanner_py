"""
直播流链接获取模块
支持B站和抖音直播平台
"""
import json
import re
import traceback
import requests
from enum import IntEnum
from typing import Tuple, Dict, Any
from core.logger import bili_log, douyin_log, error, LogLevel


class LivePlatform(IntEnum):
    """直播平台"""
    Douyin = 0  # 抖音
    BiliBili = 1  # B站


class LiveStreamStatus(IntEnum):
    """直播流状态"""
    Normal = 0
    Absent = 1      # 直播间不存在
    NotLive = 2     # 未开播
    Error = 3       # 错误


class LiveStreamInfo:
    """直播流信息"""
    def __init__(self):
        self.status = LiveStreamStatus.Normal
        self.link = ""
        self.room_id = ""
        self.title = ""
        self.uname = ""


class LiveBili:
    """B站直播获取 —— 严格对齐 C++ 版 LiveStreamLink.cpp 实现"""

    API_BASE = "https://api.live.bilibili.com"

    @staticmethod
    def douyin_qrcode_login() -> bool:
        """
        抖音二维码登录。调用抖音 API 生成登录二维码，用户手机抖音APP扫码确认后，
        自动提取 sessionid / sessionid_ss 等登录态 Cookie，
        保存到 cookie.json 的 douyin_cookie 字段。

        Returns:
            True=登录成功, False=失败/超时/取消
        """
        import time as _time
        import uuid as _uuid
        import random as _rnd
        import base64 as _b64
        import json as _json

        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "sec-ch-ua": (
                '"Chromium";v="124", "Google Chrome";v="124", '
                '"Not-A.Brand";v="99"'
            ),
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        })

        # ---- 1. 生成 msToken（douyin JS 用 base-36） ----
        _rand_part = _rnd.random()
        _rand_s = ""
        _frac = _rand_part
        for _ in range(12):
            _frac = _frac * 36
            _d = int(_frac)
            _rand_s += "0123456789abcdefghijklmnopqrstuvwxyz"[_d]
            _frac -= _d
        _ts_36 = ""
        _ts = int(_time.time() * 1000)
        _rem = _ts
        for _ in range(10):
            _rem, _d = divmod(_rem, 36)
            _ts_36 = "0123456789abcdefghijklmnopqrstuvwxyz"[_d] + _ts_36
            if _rem == 0:
                break
        ms_token = _rand_s + _ts_36

        # ---- 2. 先访问登录页获取真实 passport_csrf_token ----
        try:
            resp = session.get(
                "https://www.douyin.com/passport/login/",
                headers={"Referer": "https://www.douyin.com/"},
                timeout=15,
                allow_redirects=True,
            )
        except Exception as e:
            douyin_log(f"访问抖音登录页失败: {e}", LogLevel.ERROR)
            return False

        # passport_csrf_token
        csrf_token = session.cookies.get("passport_csrf_token", "")
        if not csrf_token:
            csrf_token = _uuid.uuid4().hex
            session.cookies.set("passport_csrf_token", csrf_token)
            douyin_log(f"未获取到 passport_csrf_token，已生成随机 token", LogLevel.INFO)

        if not session.cookies.get("ttwid"):
            _ttwid_payload = _b64.b64encode(_json.dumps({"uid": _uuid.uuid4().hex}).encode()).decode()
            session.cookies.set("ttwid", f"ttwid=1%2B{_ttwid_payload}")

        session.cookies.set("msToken", ms_token)

        # ---- 3. 生成登录二维码 ----
        def _try_get_qr():
            """尝试不同域名和参数组合获取二维码"""
            endpoints = [
                ("https://www.douyin.com/passport/qr/login/get_qrcode/", "https://www.douyin.com/passport/login/"),
                ("https://sso.douyin.com/passport/qr/login/get_qrcode/", "https://www.douyin.com/"),
            ]
            for api_url, ref_url in endpoints:
                try:
                    resp = session.get(
                        api_url,
                        params={
                            "aid": "6383",
                            "service": "https://www.douyin.com",
                            "need_logo": "false",
                            "device_platform": "web",
                            "csrf_token": csrf_token,
                            "msToken": ms_token,
                        },
                        headers={
                            "Referer": ref_url,
                            "Origin": "https://www.douyin.com",
                        },
                        timeout=15,
                    )
                    data = resp.json()
                    if data.get("message") == "success" and "data" in data:
                        return data
                    douyin_log(f"API {api_url.split('/')[2]} 返回: {data.get('data', {}).get('description', data.get('message', 'unknown'))}", LogLevel.WARN)
                except Exception as e:
                    douyin_log(f"API {api_url.split('/')[2]} 异常: {e}", LogLevel.WARN)
            return None

        data = _try_get_qr()
        if data is None:
            douyin_log("所有 API 域名都返回了错误", LogLevel.ERROR)
            return False
        qr_data = data["data"]
        qr_url = qr_data.get("qrcode", "")
        qr_token = qr_data.get("token", "")
        if not qr_url or not qr_token:
            douyin_log(f"二维码数据不完整: qrcode={bool(qr_url)}, token={bool(qr_token)}", LogLevel.ERROR)
            return False

        # ---- 3. 显示二维码 ----
        bili_log("=" * 50, LogLevel.WARN, console_only=True)
        bili_log("请使用 抖音APP 扫描下方二维码登录", LogLevel.WARN, console_only=True)

        try:
            import qrcode as _qr
            qr = _qr.QRCode(border=1)
            qr.add_data(qr_url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except ImportError:
            pass

        bili_log(f"二维码链接: {qr_url}", LogLevel.WARN, console_only=True)
        bili_log("=" * 50, LogLevel.WARN, console_only=True)

        # ---- 4. 轮询扫码状态 ----
        bili_log("等待扫码...", LogLevel.WARN, console_only=True)
        max_wait = 300
        started = _time.time()
        last_status = None

        while _time.time() - started < max_wait:
            try:
                resp = session.post(
                    "https://www.douyin.com/passport/qr/login/check_qrcode/",
                    data={
                        "csrf_token": csrf_token,
                        "token": qr_token,
                        "service": "https://www.douyin.com",
                    },
                    timeout=15,
                )
                poll = resp.json()
                status = poll.get("data", {}).get("status", "")
                extra = poll.get("data", {})

                if status == "2":
                    bili_log("扫码登录成功！正在提取 Cookie...", LogLevel.WARN, console_only=True)
                    break
                elif status == "1":
                    bili_log("二维码已过期，请重新获取", LogLevel.ERROR, console_only=True)
                    return False
                elif status == "4" and last_status != "4":
                    bili_log("已扫码，请在手机上确认登录...", LogLevel.WARN, console_only=True)
                elif status == "3" and last_status != "3":
                    pass  # waiting for scan

                last_status = status
                _time.sleep(2)
            except Exception as e:
                douyin_log(f"轮询登录状态异常: {e}", LogLevel.WARN)
                _time.sleep(2)
        else:
            bili_log("登录超时（5分钟未扫码确认）", LogLevel.ERROR, console_only=True)
            return False

        # ---- 5. 提取登录态 Cookie ----
        auth = {}
        key_fields = (
            "sessionid", "sessionid_ss", "passport_csrf_token",
            "sid_guard", "uid_tt", "sid_tt",
            "sessionid_ss", "odin_tt",
            "n_mh", "sid_ucp_v1", "ssid_ucp_v1",
        )
        for ck, cv in session.cookies.items():
            if ck in key_fields and cv:
                auth[ck] = cv
        # also include any douyin-related cookies
        for ck, cv in session.cookies.items():
            if ("session" in ck.lower() or "sid_" in ck.lower() or "uid" in ck.lower()) and ck not in auth:
                if cv:
                    auth[ck] = cv

        if not auth.get("sessionid"):
            # try sessionid_ss as fallback
            if not auth.get("sessionid_ss"):
                douyin_log(f"登录成功但未获取到关键Cookie，已获取: {list(session.cookies.keys())}", LogLevel.ERROR)
                return False

        user_cookie_str = "; ".join(f"{k}={v}" for k, v in auth.items())

        # ---- 6. 保存到 cookie.json ----
        try:
            from core.config import ConfigManager
            ConfigManager().update_douyin_cookie(user_cookie_str)
            bili_log(f"抖音登录态已保存到 douyin_cookie: {list(auth.keys())}", LogLevel.WARN, console_only=True)
            return True
        except Exception as e:
            douyin_log(f"保存登录 Cookie 失败: {e}", LogLevel.ERROR)
            return False

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.real_room_id = ""

    @staticmethod
    def _get_user_auth_cookies() -> Dict[str, str]:
        """
        尝试从配置/环境变量获取用户提供的已登录B站Cookie。
        仅提取身份认证相关的字段（SESSDATA, bili_jct, DedeUserID 等），
        用于补充HTTP获取的游客Cookie，使其具备登录态。
        
        优先级:
        1. 环境变量 BILIBILI_SESSDATA（最简单，直接设置SESSDATA值）
        2. 环境变量 BILIBILI_COOKIE（完整的 cookie 字符串）
        3. cookie.json 中的 bilibili_cookie 字段（从中提取 SESSDATA 等登录态）
        """
        import os
        auth_cookies = {}

        # 方式1: 环境变量直接设置 SESSDATA
        sessdata = os.environ.get("BILIBILI_SESSDATA", "").strip()
        if sessdata:
            auth_cookies["SESSDATA"] = sessdata
            bili_log(f"从环境变量 BILIBILI_SESSDATA 加载了 SESSDATA", LogLevel.INFO)
            return auth_cookies

        # 方式2: 环境变量设置完整 cookie
        env_cookie = os.environ.get("BILIBILI_COOKIE", "").strip()
        if env_cookie:
            for part in env_cookie.split(";"):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if k in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                        auth_cookies[k] = v
            if auth_cookies:
                bili_log(f"从环境变量 BILIBILI_COOKIE 加载了认证Cookie: {list(auth_cookies.keys())}", LogLevel.INFO)
                return auth_cookies

        # 方式3: cookie.json 中的 bilibili_cookie 字段
        try:
            from core.config import ConfigManager
            cfg = ConfigManager().config
            user_cookie = getattr(cfg, 'bilibili_cookie', '') or ''
            if user_cookie.strip():
                for part in user_cookie.split(";"):
                    part = part.strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        k = k.strip()
                        v = v.strip()
                        if k in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                            auth_cookies[k] = v
                if auth_cookies:
                    bili_log(f"从配置文件加载了认证Cookie: {list(auth_cookies.keys())}", LogLevel.INFO)
        except Exception:
            pass

        return auth_cookies

    @staticmethod
    def _refresh_session_cookies() -> str:
        """
        通过访问B站页面获取新鲜 Session Cookie（完全通过HTTP，不本地生成）。
        与抖音一致：访问首页和API，从 Set-Cookie 提取所有字段。
        失败返回空字符串。
        """
        try:
            session = requests.Session()
            session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/92.0.4515.159 Safari/537.36"
                ),
                "Referer": "https://www.bilibili.com/",
            })
            try:
                session.get("https://api.bilibili.com/x/frontend/finger/spi", timeout=8)
            except Exception:
                pass
            try:
                session.get("https://www.bilibili.com/", timeout=8, allow_redirects=True)
            except Exception:
                pass

            extracted = dict(session.cookies.items())
            if not extracted:
                bili_log("自动刷新Cookie：未收到任何 Set-Cookie", LogLevel.WARN, console_only=True)
                return ""

            cookie_str = "; ".join(f"{k}={v}" for k, v in extracted.items())
            bili_log(f"自动刷新Cookie成功，获取到 {len(extracted)} 个字段: {cookie_str[:200]}...", LogLevel.WARN, console_only=True)
            return cookie_str
        except Exception as e:
            bili_log(f"自动刷新Cookie失败: {e}", LogLevel.WARN, console_only=True)
            return ""

    # 静态默认字段（不随会话变化的常量，对标抖音 _DEFAULT_COOKIE）
    _STATIC_DEFAULTS = (
        "enable_web_push=DISABLE; "
        "header_theme_version=CLOSE; "
        "home_feed_column=5; "
        "browser_resolution=1920x1080; "
        "CURRENT_FNVAL=4048; "
        "CURRENT_QUALITY=112; "
        "bp_t_offset_="
    )

    @staticmethod
    def _generate_device_fingerprint() -> str:
        """生成本会话设备指纹Cookie（buvid4, _uuid, rpdid 等 JS 生成字段）"""
        import uuid as _uuid, time as _time, random as _random
        uid = str(_uuid.uuid4()).upper()
        ts = str(int(_time.time() * 1000))
        fp = {
            "buvid3": uid + "infoc",
            "buvid4": str(_uuid.uuid4()).upper(),
            "b_nut": ts,
            "_uuid": _uuid.uuid4().hex.upper()[:32],
            "rpdid": "|" + "|".join(
                hex(_random.randint(0, 0xFFFFFFFF))[2:].zfill(8) for _ in range(5)
            ),
            "buvid_fp": str(_random.randint(1000000000000, 9999999999999)),
            "b_lsid": str(_random.randint(1000000000000, 9999999999999)) + "_" + ts,
        }
        return "; ".join(f"{k}={v}" for k, v in fp.items())

    @classmethod
    def _merge_with_user_auth(cls, base_cookie: str) -> str:
        """将用户登录态Cookie（SESSDATA等）合并到基础Cookie中，不覆盖已有同名字段"""
        user_auth = LiveBili._get_user_auth_cookies()
        if not user_auth:
            return base_cookie

        parts = re.split(r';\s*', base_cookie) if base_cookie.strip() else []
        existing_keys = set(p.split('=', 1)[0] for p in parts if '=' in p)

        for k, v in user_auth.items():
            if k not in existing_keys:
                parts.append(f"{k}={v}")

        merged = "; ".join(parts)
        if user_auth:
            bili_log(f"已合并用户登录态Cookie: {list(user_auth.keys())}", LogLevel.DEBUG)
        return merged or base_cookie

    @classmethod
    def _get_cookie(cls) -> str:
        """
        获取B站 Cookie（不自动刷新，仅手动刷新时更新）：
        构建完整 Cookie = 设备指纹 + 静态默认值 + 配置中保存的登录态（SESSDATA等）
        已保存字段优先覆盖同名的设备指纹/静态默认值
        """
        # 1. 读取配置中已保存的 Cookie（由手动扫码登录写入，含 SESSDATA 等）
        saved = ""
        try:
            from core.config import ConfigManager
            cfg = ConfigManager().config
            saved = getattr(cfg, 'bilibili_cookie', '') or ''
        except Exception:
            pass

        # 2. 构建完整基础 Cookie：设备指纹 + 静态默认值
        fp = cls._generate_device_fingerprint()
        base = fp + "; " + cls._STATIC_DEFAULTS

        if saved.strip():
            # 已保存的字段优先覆盖基础 Cookie 中的同名字段
            saved_keys = set(p.split('=', 1)[0] for p in re.split(r';\s*', saved) if '=' in p)
            base_parts = [p for p in re.split(r';\s*', base) if '=' in p and p.split('=', 1)[0] not in saved_keys]
            merged = "; ".join(base_parts) + "; " + saved
        else:
            merged = base

        # 3. 合并环境变量中可能的额外登录态
        return cls._merge_with_user_auth(merged)

    @staticmethod
    def bilibili_qrcode_login() -> bool:
        """
        B站二维码登录。调用 B站 API 生成登录二维码，用户手机扫码确认后，
        自动提取 SESSDATA / bili_jct / DedeUserID 等登录态 Cookie，
        保存到 cookie.json 的 bilibili_cookie 字段。

        Returns:
            True=登录成功, False=失败/超时/取消
        """
        import time as _time

        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        })

        # ---- 1. 生成二维码 ----
        try:
            resp = session.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
                timeout=10,
            )
            data = resp.json()
            if data.get("code") != 0:
                bili_log(f"生成登录二维码失败: {data}", LogLevel.ERROR)
                return False
            qr_url = data["data"]["url"]
            qr_key = data["data"]["qrcode_key"]
        except Exception as e:
            bili_log(f"获取登录二维码异常: {e}", LogLevel.ERROR)
            return False

        # ---- 2. 显示二维码 ----
        bili_log("=" * 50, LogLevel.WARN, console_only=True)
        bili_log("请使用 B站APP 扫描下方二维码登录", LogLevel.WARN, console_only=True)

        # 尝试终端 ASCII 二维码
        try:
            import qrcode as _qr
            qr = _qr.QRCode(border=1)
            qr.add_data(qr_url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except ImportError:
            pass

        bili_log(f"二维码链接: {qr_url}", LogLevel.WARN, console_only=True)
        bili_log("(安装 qrcode[pil] 可在终端显示二维码图: pip install qrcode[pil])", LogLevel.INFO, console_only=True)
        bili_log("=" * 50, LogLevel.WARN, console_only=True)

        # ---- 3. 轮询扫码状态（B站二维码有效期 180s） ----
        bili_log("等待扫码...", LogLevel.WARN, console_only=True)
        max_wait = 180
        started = _time.time()
        last_state = -1

        while _time.time() - started < max_wait:
            try:
                resp = session.get(
                    "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                    params={"qrcode_key": qr_key},
                    timeout=10,
                )
                poll = resp.json()
                code = poll.get("data", {}).get("code", poll.get("code", -1))

                if code == 0:
                    bili_log("扫码登录成功！正在提取 Cookie...", LogLevel.WARN, console_only=True)
                    break
                elif code == 86038:
                    bili_log("二维码已过期，请重新获取", LogLevel.ERROR, console_only=True)
                    return False
                elif code == 86090 and last_state != 86090:
                    bili_log("已扫码，请在手机上确认登录...", LogLevel.WARN, console_only=True)
                elif code == 86101 and last_state != 86101:
                    pass  # 等待扫码，不重复输出

                last_state = code
                _time.sleep(2)
            except Exception as e:
                bili_log(f"轮询登录状态异常: {e}", LogLevel.WARN)
                _time.sleep(2)
        else:
            bili_log("登录超时（3分钟未扫码确认）", LogLevel.ERROR, console_only=True)
            return False

        # ---- 4. 提取登录态 Cookie ----
        auth = {}
        for ck, cv in session.cookies.items():
            if ck in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                if cv:
                    auth[ck] = cv

        if not auth.get("SESSDATA"):
            bili_log("登录成功但未获取到 SESSDATA，请重试", LogLevel.ERROR)
            return False

        user_cookie_str = "; ".join(f"{k}={v}" for k, v in auth.items())

        # ---- 5. 保存到 cookie.json 的 bilibili_cookie ----
        try:
            from core.config import ConfigManager
            ConfigManager().update_bilibili_cookie(user_cookie_str)
            bili_log(f"B站登录态已保存到 bilibili_cookie: {list(auth.keys())}", LogLevel.WARN, console_only=True)
        except Exception as e:
            bili_log(f"保存登录 Cookie 失败: {e}", LogLevel.ERROR)
            return False

        return True

    def _get_stream_url(self, params: Dict[str, str]) -> str:
        """
        从 getRoomPlayInfo 响应中提取拼接流URL
        """
        url = f"{self.API_BASE}/xlive/web-room/v2/index/getRoomPlayInfo"
        try:
            cookie = self._get_cookie()
            headers = {
                "Cookie": cookie,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Referer": "https://live.bilibili.com/",
                "Origin": "https://live.bilibili.com",
            }
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200 or not resp.text:
                bili_log(f"getRoomPlayInfo HTTP状态={resp.status_code}, text={resp.text[:200] if resp.text else '(空)'}", LogLevel.WARN)
                return ""

            play_info = resp.json()
            code = play_info.get("code", -1)
            msg = play_info.get("message", "")
            bili_log(f"getRoomPlayInfo API code={code}, message={msg}", LogLevel.DEBUG)

            if code != 0:
                bili_log(f"getRoomPlayInfo 返回错误码: code={code}, message={msg}", LogLevel.WARN)
                # 需要登录 → 自动触发二维码登录
                if code == -101 or "登录" in msg:
                    bili_log("⚠ B站游客Cookie无法获取直播流", LogLevel.ERROR)
                    try:
                        from core.config import ConfigManager
                        cfg = ConfigManager().config
                        existing = (getattr(cfg, 'bilibili_cookie', '') or '').strip()
                        if existing:
                            bili_log("已有登录态但依然失败，可能是 SESSDATA 已过期，请重新登录", LogLevel.ERROR)
                        else:
                            bili_log("未检测到B站登录态，自动尝试二维码登录...", LogLevel.WARN, console_only=True)
                            if LiveBili.bilibili_qrcode_login():
                                self._just_logged_in = True
                    except Exception:
                        pass
                return ""

            data = play_info.get("data", {})
            playurl_info = data.get("playurl_info", {})
            playurl = playurl_info.get("playurl", {})

            try:
                stream_list = playurl["stream"]
                stream = stream_list[0]
                format_list = stream["format"]
                fmt = format_list[0]
                codec_list = fmt["codec"]
                codec = codec_list[0]
            except (KeyError, IndexError, TypeError) as e:
                bili_log(f"解析流结构失败: {e}, playurl keys={list(playurl.keys()) if isinstance(playurl, dict) else type(playurl).__name__}", LogLevel.WARN)
                # 输出简要的 playurl 结构帮助调试
                if isinstance(playurl, dict) and not playurl:
                    bili_log("playurl 为空字典 —— 大概率是游客Cookie无法获取流，需要登录B站账号", LogLevel.ERROR)
                return ""

            base_url = codec.get("base_url", "")
            url_info_list = codec.get("url_info", [])
            if not url_info_list:
                bili_log("url_info 为空", LogLevel.WARN)
                return ""
            extra = url_info_list[0].get("extra", "")
            host = url_info_list[0].get("host", "")

            full_url = host + base_url + extra
            bili_log(f"流地址: {full_url[:60]}...", LogLevel.DEBUG)
            return full_url

        except Exception as e:
            bili_log(f"GetStreamUrl 异常: {e}", LogLevel.DEBUG)
            return ""

    def get_live_stream_info(self) -> LiveStreamInfo:
        """
        获取B站直播流信息
        严格对应 C++ 版 LiveBili::GetLiveStreamInfo()
        """
        info = LiveStreamInfo()
        info.room_id = self.room_id

        try:
            # 获取 Cookie（供后续请求使用）
            cookie = self._get_cookie()
            headers = {
                "Cookie": cookie,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Referer": "https://live.bilibili.com/",
                "Origin": "https://live.bilibili.com",
            } if cookie else {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            }

            # ---- 第1步: room_init 获取房间初始化信息 ----
            room_init_url = f"{self.API_BASE}/room/v1/Room/room_init"
            resp = requests.get(room_init_url, params={"id": self.room_id}, headers=headers, timeout=10)

            bili_log(f"room_init HTTP状态={resp.status_code}, text_len={len(resp.text) if resp.text else 0}", LogLevel.DEBUG)

            if resp.status_code != 200 or not resp.text:
                bili_log(f"room_init 请求失败: status={resp.status_code}, text={'空' if not resp.text else resp.text[:200]}", LogLevel.WARN)
                info.status = LiveStreamStatus.Error
                return info

            room_info = resp.json()
            code = room_info.get("code", -1)
            bili_log(f"room_init code={code}", LogLevel.DEBUG)

            # code == 60004 表示直播间不存在
            if code == 60004:
                bili_log(f"直播间不存在: room_id={self.room_id}", LogLevel.WARN)
                info.status = LiveStreamStatus.Absent
                return info

            if code != 0:
                bili_log(f"room_init 返回异常: code={code}, message={room_info.get('message', '')}", LogLevel.WARN)
                info.status = LiveStreamStatus.Error
                return info

            data = room_info.get("data", {})
            live_status = data.get("live_status", 0)
            bili_log(f"live_status={live_status} (1=直播中)", LogLevel.DEBUG)

            # live_status != 1 表示未开播
            if live_status != 1:
                info.status = LiveStreamStatus.NotLive
                return info

            # 更新真实房间号
            if "room_id" in data:
                self.real_room_id = str(data["room_id"])

            bili_log(f"房间在直播 (live_status=1)，开始获取流地址 real_room_id={self.real_room_id}...", LogLevel.DEBUG)

            # ---- 第2步: GetLinkByRealRoomID ----
            # C++ 参数: codec=0, format=0,2, only_audio=0, only_video=0, protocol=0,1, qn=10000, room_id
            play_params = {
                "codec": "0",
                "format": "0,2",
                "only_audio": "0",
                "only_video": "0",
                "protocol": "0,1",
                "qn": "10000",
                "room_id": self.real_room_id,
            }

            link = self._get_stream_url(play_params)
            # 二维码登录成功后自动重试一次
            if not link and getattr(self, '_just_logged_in', False):
                self._just_logged_in = False
                bili_log("登录成功，自动重试获取直播流...", LogLevel.WARN, console_only=True)
                link = self._get_stream_url(play_params)
            if link:
                info.status = LiveStreamStatus.Normal
                info.link = link
            else:
                bili_log("getRoomPlayInfo 未能获取流地址（可能需要登录或Cookie过期）", LogLevel.WARN)
                info.status = LiveStreamStatus.Error

            return info

        except json.JSONDecodeError:
            bili_log("room_init 响应 JSON 解析失败", LogLevel.WARN)
            info.status = LiveStreamStatus.Error
            return info
        except Exception as e:
            error(f"获取B站直播流失败: {e}\n{traceback.format_exc()}")
            info.status = LiveStreamStatus.Error
            return info

    def get_live_stream_url(self) -> Tuple[LiveStreamStatus, str]:
        """获取B站直播流URL，返回 (状态, URL)"""
        info = self.get_live_stream_info()
        return info.status, info.link

    def get_room_info(self) -> Dict[str, Any]:
        """获取直播间信息"""
        if not self.real_room_id:
            self.get_real_room_id()  # 调用空实现保持兼容
        if not self.real_room_id:
            return {}

        url = f"{self.API_BASE}/room/v1/Room/get_info"
        params = {"room_id": self.real_room_id}
        try:
            cookie = self._get_cookie()
            headers = {"Cookie": cookie} if cookie else {}
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            if result.get("code") == 0:
                return result.get("data", {})
            return {}
        except Exception:
            return {}

    def get_real_room_id(self) -> str:
        """获取真实房间号（保持兼容）"""
        if self.real_room_id:
            return self.real_room_id
        # 通过 room_init 获取
        try:
            resp = requests.get(
                f"{self.API_BASE}/room/v1/Room/room_init",
                params={"id": self.room_id}, timeout=10
            )
            result = resp.json()
            if result.get("code") == 0:
                self.real_room_id = str(result["data"]["room_id"])
                return self.real_room_id
        except Exception:
            pass
        return ""


class LiveDouyin:
    """抖音直播获取 —— 严格对齐 C++ 版 LiveStreamLink.cpp 实现"""

    BASE_URL = "https://live.douyin.com"

    # 硬编码的默认 Cookie（兜底，仅在所有其他来源都失败时使用）
    _DEFAULT_COOKIE = (
        "enter_pc_once=1; "
        "UIFID_TEMP=29a1f63ec682dc0a0df227dd163e2b46e3a6390e403335fa4c2c6d1dc0ec5ffa7a288170e8828ecb8b2f0f16b3219daa18ad5d7faf7fb5fbb64df454c3b471cc1db9c0b5eb2cbc8e0cb1e690f5c1fbd6; "
        "stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A2560%2C%5C%22screen_height%5C%22%3A1440%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A16%2C%5C%22device_memory%5C%22%3A8%2C%5C%22downlink%5C%22%3A10%2C%5C%22effective_type%5C%22%3A%5C%224g%5C%22%2C%5C%22round_trip_time%5C%22%3A50%7D%22; "
        "hevc_supported=true; "
        "odin_tt=363047b47492a2e153d67e7022684ffd83726a0c57322991e6650da1dbe2fc0adb471e8be38efa85bf0ab9788a8e237d481c8fc488ef859f4476fc6ffd50dd31a258add2954b3fcf03cd546357df6a53; "
        "strategyABtestKey=%221772897157.15%22; "
        "passport_csrf_token=d71952d93315e4df5cc8373e4cdc2447; "
        "passport_csrf_token_default=d71952d93315e4df5cc8373e4cdc2447; "
        "home_can_add_dy_2_desktop=%221%22; "
        "biz_trace_id=fab9d888; "
        "ttwid=1%7CP0feYUzzIsbXr2aaLLBWHYtwVD4-6CV2voO9bAUQ7PU%7C1772897161%7Cd72bed8f6f576a1dfb7b8d1032c76706ce93b3ba3ac5b21e79501db1c2f17c9f; "
        "__security_mc_1_s_sdk_crypt_sdk=0ef27763-40a0-b3c3; "
        "bd_ticket_guard_client_data=eyJiZC10aWNrZXQtZ3VhcmQtdmVyc2lvbiI6MiwiYmQtdGlja2V0LWd1YXJkLWl0ZXJhdGlvbi12ZXJzaW9uIjoxLCJiZC10aWNrZXQtZ3VhcmQtcmVlLXB1YmxpYy1rZXkiOiJCSjhja053TW16SWxIVWQzazF4d2F6bXdQdm1JZjUrcElEVWR2MmpTN3czVWRKRWZ6djBIN1g5Z3dINUNnRkpSSGIzOEFvWTZYSEZsOEdWcGd1dmN4OGc9IiwiYmQtdGlja2V0LWd1YXJkLXdlYi12ZXJzaW9uIjoyfQ%3D%3D; "
        "bd_ticket_guard_client_web_domain=2; "
        "bd_ticket_guard_client_data_v2=eyJyZWVfcHVibGljX2tleSI6IkJKOGNrTndNbXpJbEhVZDNrMXh3YXptd1B2bUlmNStwSURVZHYyalM3dzNVZEpFZnp2MEg3WDlnd0g1Q2dGSlJIYjM4QW9ZNlhIRmw4R1ZwZ3V2Y3g4Zz0iLCJyZXFfY29udGVudCI6InNlY190cyIsInJlcV9zaWduIjoiNkxSc0hxbFZ4bUhHSFVzMCtsQ0dLaGNlU242bVZxZzRRRFJmdjJ1RzZCaz0iLCJzZWNfdHMiOiIjaUZua3E0M0pNV25FWGlQNW15b3grVTlWdUNrL3B4ZnQveVlsL3o5eWdpWnRSOUZjbEZSSmFGOXk1T1lWIn0%3D; "
        "sdk_source_info=7e276470716a68645a606960273f276364697660272927676c715a6d6069756077273f276364697660272927666d776a68605a607d71606b766c6a6b5a7666776c7571273f275e58272927666a6b766a69605a696c6061273f27636469766027292762696a6764695a7364776c6467696076273f275e582729277672715a646971273f2763646976602729277f6b5a666475273f2763646976602729276d6a6e5a6b6a716c273f2763646976602729276c6b6f5a7f6367273f27636469766027292771273f27343636343334323c3d37323234272927676c715a75776a716a666a69273f2763646976602778; "
        "bit_env=7NCrRegY020LGVG5Yx8HFRWB73RARpFbj-iyQ1LwqU0cDI9moZj9ecPpsbpkSaMTEyZqsilIKiI_lt70BB_G6Dod7wN8rkLhE631Bz9wC_ixgEAlNeIdElXvK3C9gool9MEa3Y5xuHt4r36Y7HkF5YAELvmsxcB8412Lfy3XuXNgybsvbLqhJrUhs-rG5nU1V-xyc70ffKH2TqV_ZxyfiI1Qn7a3LENvJkf8V9ntSbLM3qoKcG5so8A6lMQ5LoyEsZgIq4i-rMHEO1Bc13y9wvk3oi-sJI76Ez-qeR_ArnBjdI6ZLTG_MUWfLeu9Ikz79n1nYgUl8r6sEXw3L3au4iOY5cfKhxFNEOszmGtoiAE8n91LvALTHWW_yZgi93E_ne4h-gOaqKLccAN05tCphxDc1uAoS3i4jBcKdnyF6ZVyGuJ_FSi4NQFvVGupfejzLbrfZoWDfGj6pgZpGEMCHnF0w_ajPy3jko_TKwdpi7DW6q49w-fjUYSjc3vJ137yj0N3um5dVKvIFJM1v0yBsavXNheto_S1GKCVq-6LTcM%3D; "
        "gulu_source_res=eyJwX2luIjoiOWYxNmJiYTEwNTIwMTgyMzIwOGMyZWYyYzllN2RkYWE1YjRjNTgzYmI0ZDhkYzAwNWNlODQxZjgwNTU3MzA5ZCJ9; "
        "passport_auth_mix_state=nt3zeeuup2eyy8cn750jdgpj52a9ldxlw3vzw45ba2eu8j77; "
        "is_dash_user=1; "
        "x-web-secsdk-uid=17063330-58d4-4719-9971-dba52fc661ab; "
        "__live_version__=%221.1.4.9549%22; "
        "has_avx2=null; "
        "device_web_cpu_core=16; "
        "device_web_memory_size=8; "
        "webcast_local_quality=null; "
        "live_use_vvc=%22false%22; "
        "csrf_session_id=5fe8f9d1180e55817920dae0808993ba; "
        "live_debug_info=%7B%22roomId%22%3A%227614515520083118863%22%2C%22resolution%22%3A%7B%22width%22%3A1920%2C%22height%22%3A1080%7D%2C%22fps%22%3A70%2C%22audioDataRate%22%3A48000%2C%22droppedFrames%22%3A4%2C%22totalFrames%22%3A65%2C%22videoBuffer%22%3A%5B%5D%2C%22src%22%3A%22https%3A%2F%2Fpull-flv-q13.douyincdn.com%2Fthirdgame%2Fstream-695437557938520894.flv%3Farch_hrchy%3Dh1%26exp_hrchy%3Dh1%26expire%3D1773502023%26major_anchor_level%3Dcommon%26sign%3D5d4807ba64265f674729e812ec33618c%26t_id%3D037-202603072327037BDC1553A514D5F37F8C-QZsvPZ%26unique_id%3Dstream-695437557938520894_830_flv%26_session_id%3D037-202603072327037BDC1553A514D5F37F8C-QZsvPZ.1772897224232.33396%26rsi%3D1%26abr_pts%3D-800%22%2C%22linkmicInfo%22%3A%7B%22uiLayout%22%3A0%2C%22playModes%22%3A%5B%5D%2C%22allDevices%22%3A%22%E8%BF%9E%E7%BA%BF%E8%AE%BE%E5%A4%87%EF%BC%9A%E7%94%B3%E8%AF%B7%E8%BF%9E%E7%BA%BF%E5%90%8E%E6%89%8D%E8%8E%B7%E5%8F%96%22%2C%22audioInputs%22%3A%5B%5D%2C%22videoInputs%22%3A%5B%5D%7D%2C%22href%22%3A%22https%3A%2F%2Flive.douyin.com%2F262229562462%3Fanchor_id%3D60708713854%26follow_status%3D0%26is_vs%3D0%26vs_ep_group_id%3D%26vs_episode_id%3D%26vs_episode_stage%3D%26vs_season_id%3D%22%7D; "
        "fpk1=U2FsdGVkX19Xphctu6x8/IFxEj3mGvQobR7U2Gy90RThMds9G7h1ZgbvhsMLPFfJL+8+eZ5CzEghbCVjENUCnA==; "
        "fpk2=800cce95768a9a4605cb3f6b181e9057; "
        "h265ErrorNum=-1; "
        "webcast_leading_last_show_time=1772897235315; "
        "webcast_leading_total_show_times=1; "
        "IsDouyinActive=false; "
        "live_can_add_dy_2_desktop=%220%22"
    )

    @staticmethod
    def douyin_qrcode_login() -> bool:
        """
        抖音二维码登录。调用抖音 API 生成登录二维码，用户手机抖音APP扫码确认后，
        自动提取 sessionid / sessionid_ss 等登录态 Cookie，
        保存到 cookie.json 的 douyin_cookie 字段。

        Returns:
            True=登录成功, False=失败/超时/取消
        """
        import time as _time
        import uuid as _uuid
        import random as _rnd
        import base64 as _b64
        import json as _json

        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "sec-ch-ua": (
                '"Chromium";v="124", "Google Chrome";v="124", '
                '"Not-A.Brand";v="99"'
            ),
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        })

        # ---- 1. 生成 msToken（douyin JS 用 base-36） ----
        _rand_part = _rnd.random()
        _rand_s = ""
        _frac = _rand_part
        for _ in range(12):
            _frac = _frac * 36
            _d = int(_frac)
            _rand_s += "0123456789abcdefghijklmnopqrstuvwxyz"[_d]
            _frac -= _d
        _ts_36 = ""
        _ts = int(_time.time() * 1000)
        _rem = _ts
        for _ in range(10):
            _rem, _d = divmod(_rem, 36)
            _ts_36 = "0123456789abcdefghijklmnopqrstuvwxyz"[_d] + _ts_36
            if _rem == 0:
                break
        ms_token = _rand_s + _ts_36

        # ---- 2. 先访问登录页获取真实 passport_csrf_token ----
        try:
            resp = session.get(
                "https://www.douyin.com/passport/login/",
                headers={"Referer": "https://www.douyin.com/"},
                timeout=15,
                allow_redirects=True,
            )
        except Exception as e:
            douyin_log(f"访问抖音登录页失败: {e}", LogLevel.ERROR)
            return False

        # passport_csrf_token
        csrf_token = session.cookies.get("passport_csrf_token", "")
        if not csrf_token:
            csrf_token = _uuid.uuid4().hex
            session.cookies.set("passport_csrf_token", csrf_token)
            douyin_log(f"未获取到 passport_csrf_token，已生成随机 token", LogLevel.INFO)

        if not session.cookies.get("ttwid"):
            _ttwid_payload = _b64.b64encode(_json.dumps({"uid": _uuid.uuid4().hex}).encode()).decode()
            session.cookies.set("ttwid", f"ttwid=1%2B{_ttwid_payload}")

        session.cookies.set("msToken", ms_token)

        # ---- 3. 生成登录二维码 ----
        def _try_get_qr():
            """尝试不同域名和参数组合获取二维码"""
            endpoints = [
                ("https://www.douyin.com/passport/qr/login/get_qrcode/", "https://www.douyin.com/passport/login/"),
                ("https://sso.douyin.com/passport/qr/login/get_qrcode/", "https://www.douyin.com/"),
            ]
            for api_url, ref_url in endpoints:
                try:
                    resp = session.get(
                        api_url,
                        params={
                            "aid": "6383",
                            "service": "https://www.douyin.com",
                            "need_logo": "false",
                            "device_platform": "web",
                            "csrf_token": csrf_token,
                            "msToken": ms_token,
                        },
                        headers={
                            "Referer": ref_url,
                            "Origin": "https://www.douyin.com",
                        },
                        timeout=15,
                    )
                    data = resp.json()
                    if data.get("message") == "success" and "data" in data:
                        return data
                    douyin_log(f"API {api_url.split('/')[2]} 返回: {data.get('data', {}).get('description', data.get('message', 'unknown'))}", LogLevel.WARN)
                except Exception as e:
                    douyin_log(f"API {api_url.split('/')[2]} 异常: {e}", LogLevel.WARN)
            return None

        data = _try_get_qr()
        if data is None:
            douyin_log("所有 API 域名都返回了错误", LogLevel.ERROR)
            return False
        qr_data = data["data"]
        qr_url = qr_data.get("qrcode", "")
        qr_token = qr_data.get("token", "")
        if not qr_url or not qr_token:
            douyin_log(f"二维码数据不完整: qrcode={bool(qr_url)}, token={bool(qr_token)}", LogLevel.ERROR)
            return False

        # ---- 3. 显示二维码 ----
        bili_log("=" * 50, LogLevel.WARN, console_only=True)
        bili_log("请使用 抖音APP 扫描下方二维码登录", LogLevel.WARN, console_only=True)

        try:
            import qrcode as _qr
            qr = _qr.QRCode(border=1)
            qr.add_data(qr_url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except ImportError:
            pass

        bili_log(f"二维码链接: {qr_url}", LogLevel.WARN, console_only=True)
        bili_log("=" * 50, LogLevel.WARN, console_only=True)

        # ---- 4. 轮询扫码状态 ----
        bili_log("等待扫码...", LogLevel.WARN, console_only=True)
        max_wait = 300
        started = _time.time()
        last_status = None

        while _time.time() - started < max_wait:
            try:
                resp = session.post(
                    "https://www.douyin.com/passport/qr/login/check_qrcode/",
                    data={
                        "csrf_token": csrf_token,
                        "token": qr_token,
                        "service": "https://www.douyin.com",
                    },
                    timeout=15,
                )
                poll = resp.json()
                status = poll.get("data", {}).get("status", "")
                extra = poll.get("data", {})

                if status == "2":
                    bili_log("扫码登录成功！正在提取 Cookie...", LogLevel.WARN, console_only=True)
                    break
                elif status == "1":
                    bili_log("二维码已过期，请重新获取", LogLevel.ERROR, console_only=True)
                    return False
                elif status == "4" and last_status != "4":
                    bili_log("已扫码，请在手机上确认登录...", LogLevel.WARN, console_only=True)
                elif status == "3" and last_status != "3":
                    pass  # waiting for scan

                last_status = status
                _time.sleep(2)
            except Exception as e:
                douyin_log(f"轮询登录状态异常: {e}", LogLevel.WARN)
                _time.sleep(2)
        else:
            bili_log("登录超时（5分钟未扫码确认）", LogLevel.ERROR, console_only=True)
            return False

        # ---- 5. 提取登录态 Cookie ----
        auth = {}
        key_fields = (
            "sessionid", "sessionid_ss", "passport_csrf_token",
            "sid_guard", "uid_tt", "sid_tt",
            "sessionid_ss", "odin_tt",
            "n_mh", "sid_ucp_v1", "ssid_ucp_v1",
        )
        for ck, cv in session.cookies.items():
            if ck in key_fields and cv:
                auth[ck] = cv
        # also include any douyin-related cookies
        for ck, cv in session.cookies.items():
            if ("session" in ck.lower() or "sid_" in ck.lower() or "uid" in ck.lower()) and ck not in auth:
                if cv:
                    auth[ck] = cv

        if not auth.get("sessionid"):
            # try sessionid_ss as fallback
            if not auth.get("sessionid_ss"):
                douyin_log(f"登录成功但未获取到关键Cookie，已获取: {list(session.cookies.keys())}", LogLevel.ERROR)
                return False

        user_cookie_str = "; ".join(f"{k}={v}" for k, v in auth.items())

        # ---- 6. 保存到 cookie.json ----
        try:
            from core.config import ConfigManager
            ConfigManager().update_douyin_cookie(user_cookie_str)
            bili_log(f"抖音登录态已保存到 douyin_cookie: {list(auth.keys())}", LogLevel.WARN, console_only=True)
            return True
        except Exception as e:
            douyin_log(f"保存登录 Cookie 失败: {e}", LogLevel.ERROR)
            return False

    def __init__(self, room_id: str):
        self.room_id = room_id

    @staticmethod
    def _refresh_session_cookies() -> str:
        """
        通过访问抖音首页获取新鲜 Session Cookie（ttwid 等）。
        返回从 Set-Cookie 头提取的 Cookie 字符串，失败返回 ""。
        """
        try:
            session = requests.Session()
            session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/92.0.4515.159 Safari/537.36"
                ),
            })
            resp = session.get("https://live.douyin.com/", timeout=10, allow_redirects=True)
            # 从 Set-Cookie 中提取关键 cookie 值
            extracted = {}
            for r in resp.history + [resp]:
                for cookie_name, cookie_val in session.cookies.items():
                    extracted[cookie_name] = cookie_val

            if not extracted:
                douyin_log("自动刷新Cookie：未收到任何 Set-Cookie", LogLevel.WARN, console_only=True)
                return ""

            # 组装成 key=value; key=value... 字符串
            cookie_str = "; ".join(f"{k}={v}" for k, v in extracted.items())
            douyin_log(f"自动刷新Cookie成功，获取到 {len(extracted)} 个字段: {cookie_str[:200]}...", LogLevel.WARN, console_only=True)
            return cookie_str
        except Exception as e:
            douyin_log(f"自动刷新Cookie失败: {e}", LogLevel.WARN, console_only=True)
            return ""

    @classmethod
    def _get_cookie(cls) -> str:
        """
        获取抖音 Cookie（不自动刷新，仅手动刷新时更新）：
        1. config.json 中手动刷新保存的 douyin_cookie
        2. 内置默认 Cookie（最终兜底）
        """
        # 1. 使用配置中保存的 douyin_cookie（由手动刷新写入）
        try:
            from core.config import ConfigManager
            cfg = ConfigManager().config
            if cfg.douyin_cookie and cfg.douyin_cookie.strip():
                return cfg.douyin_cookie
        except Exception:
            pass

        # 2. 兜底：使用内置默认 Cookie
        douyin_log("使用内置默认Cookie（无已保存Cookie）", LogLevel.WARN, console_only=True)
        return cls._DEFAULT_COOKIE

    def _get_stream_link_from_response(self, data: dict) -> str:
        """
        从 API 响应 data 中提取 FLV 流地址
        严格对应 C++ 版 GetStreamLinkFromResponse()
        """
        try:
            stream_url = data.get("stream_url", {})

            # 方式1: pull_datas -> stream_data (内嵌JSON) -> origin.main.flv
            pull_datas = stream_url.get("pull_datas")
            if pull_datas:
                # pull_datas 是一个 dict，取第一个value
                for key, double_screen_streams in pull_datas.items():
                    stream_data_str = double_screen_streams.get("stream_data", "")
                    if stream_data_str:
                        stream_data = json.loads(stream_data_str)
                        flv_url = stream_data["data"]["origin"]["main"]["flv"]
                        douyin_log(f"FLV流地址(pull_datas): {flv_url[:60]}...", LogLevel.DEBUG)
                        return flv_url
                    break  # 只取第一个（与 C++ 的 pullDatas.begin() 一致）

            # 方式2: live_core_sdk_data -> pull_data.stream_data (内嵌JSON) -> origin.main.flv
            live_core = stream_url.get("live_core_sdk_data")
            if live_core:
                stream_data_str = live_core.get("pull_data", {}).get("stream_data", "")
                if stream_data_str:
                    stream_data = json.loads(stream_data_str)
                    flv_url = stream_data["data"]["origin"]["main"]["flv"]
                    douyin_log(f"FLV流地址(live_core_sdk): {flv_url[:60]}...", LogLevel.DEBUG)
                    return flv_url

            return ""
        except Exception as e:
            douyin_log(f"解析流地址异常: {e}", LogLevel.DEBUG)
            return ""

    def get_live_stream_info(self) -> LiveStreamInfo:
        """
        获取抖音直播流信息
        严格对应 C++ 版 LiveDouyin::GetLiveStreamInfo()
        """
        info = LiveStreamInfo()
        info.room_id = self.room_id

        try:
            # ---- 构建请求参数（与C++完全一致） ----
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36"
            )

            headers = {
                "User-Agent": user_agent,
                "Referer": "https://live.douyin.com/",
                "Cookie": self._get_cookie(),
            }

            params = {
                "aid": "6383",
                "app_name": "douyin_web",
                "live_id": "1",
                "device_platform": "web",
                "browser_language": "zh-CN",
                "browser_platform": "Win32",
                "browser_name": "Edge",
                "browser_version": "139.0.0.0",
                "is_need_double_stream": "false",
                "web_rid": self.room_id,
            }

            api_url = f"{self.BASE_URL}/webcast/room/web/enter/"
            douyin_log(f"请求 API: web_rid={self.room_id}", LogLevel.DEBUG)

            resp = requests.get(api_url, params=params, headers=headers, timeout=15)
            douyin_log(f"API HTTP 状态码: {resp.status_code}", LogLevel.DEBUG)

            if resp.status_code != 200 or not resp.text:
                douyin_log("API 请求失败或无响应", LogLevel.WARN)
                info.status = LiveStreamStatus.Error
                return info

            result = resp.json()
            status_code = result.get("status_code", -1)
            douyin_log(f"API status_code: {status_code}", LogLevel.DEBUG)

            if status_code != 0:
                douyin_log(f"API 返回非0状态码: {status_code}, message: {result.get('message', '')}", LogLevel.WARN)
                info.status = LiveStreamStatus.Absent
                return info

            # C++ 解析路径: streamInfo["data"]["data"][0]
            data_list = result.get("data", {}).get("data", [])
            if not data_list:
                douyin_log("data.data 为空", LogLevel.WARN)
                info.status = LiveStreamStatus.Error
                return info

            room_data = data_list[0]
            status = room_data.get("status", 0)
            douyin_log(f"直播间状态: {status} (2=直播中, 4=未开播)", LogLevel.DEBUG)

            # status == 2: 开播
            if status == 2:
                link = self._get_stream_link_from_response(room_data)
                if link:
                    info.status = LiveStreamStatus.Normal
                    info.link = link
                else:
                    douyin_log("流地址解析失败", LogLevel.WARN)
                    info.status = LiveStreamStatus.Error
                return info

            # status == 4: 未开播
            elif status == 4:
                info.status = LiveStreamStatus.NotLive
                return info

            # 其他状态
            info.status = LiveStreamStatus.Error
            return info

        except json.JSONDecodeError:
            douyin_log("API 返回非 JSON 内容", LogLevel.WARN)
            info.status = LiveStreamStatus.Error
            return info
        except Exception as e:
            error(f"获取抖音直播流失败: {e}\n{traceback.format_exc()}")
            info.status = LiveStreamStatus.Error
            return info

    def get_live_stream_url(self) -> Tuple[LiveStreamStatus, str]:
        """
        获取抖音直播流URL
        封装 get_live_stream_info()，返回 (状态, URL) 元组
        """
        info = self.get_live_stream_info()
        return info.status, info.link

    def get_room_info(self) -> Dict[str, Any]:
        """获取直播间信息（通过 API）"""
        try:
            info = self.get_live_stream_info()
            # get_live_stream_info 已经调用了 API，这里简化返回
            return {
                "title": "",
                "nickname": "",
                "status": 2 if info.status == LiveStreamStatus.Normal else 0
            }
        except Exception:
            return {}


def get_live_info(platform: LivePlatform, room_id: str) -> LiveStreamInfo:
    """
    获取直播流信息
    
    Args:
        platform: 直播平台
        room_id: 直播间ID
    
    Returns:
        LiveStreamInfo对象
    """
    if platform == LivePlatform.BiliBili:
        return LiveBili(room_id).get_live_stream_info()
    elif platform == LivePlatform.Douyin:
        return LiveDouyin(room_id).get_live_stream_info()
    else:
        info = LiveStreamInfo()
        info.status = LiveStreamStatus.Error
        return info


def get_stream_url_for_ffmpeg(platform: LivePlatform, room_id: str) -> Tuple[LiveStreamStatus, str]:
    """
    获取可用于FFmpeg的直播流URL
    
    Args:
        platform: 直播平台
        room_id: 直播间ID
    
    Returns:
        (状态, 流URL)
    """
    if platform == LivePlatform.Douyin:
        return LiveDouyin(room_id).get_live_stream_url()
    elif platform == LivePlatform.BiliBili:
        bili = LiveBili(room_id)
        return bili.get_live_stream_url()
    else:
        return LiveStreamStatus.Error, ""


if __name__ == "__main__":
    """独立运行：B站二维码登录工具"""
    import sys as _sys
    import os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    print()
    LiveBili.bilibili_qrcode_login()
