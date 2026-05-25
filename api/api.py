"""
米哈游API调用模块
"""
import json
import time
import random
import hashlib
import requests
from enum import IntEnum
from typing import Optional, Tuple, Dict, Any
from urllib.parse import urlencode
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from core.logger import api_log, qr_log, debug, info, warn, error, LogLevel

# 尝试使用 curl_cffi 模拟 libcurl TLS 指纹（与 C++ 一致），绕过 miHoYo WAF -3503
try:
    from curl_cffi import requests as curl_requests  # type: ignore
    _USE_CURL_CFFI = True
except ImportError:
    curl_requests = None  # type: ignore
    _USE_CURL_CFFI = False

def _safe_post(url: str, json_data: dict, headers: dict, timeout: int = 10):
    """HTTP POST 请求（对齐 C++ cpr::Post — 每次新建连接，无持久 Session）

    C++ 使用 cpr::Post()（大写P，free function），每次创建临时 Session → 独立连接。
    Python 之前用 curl_cffi.Session() 持久连接复用，TLS 会话恢复行为易被 WAF
    识别为持续轮询机器人。改为每次新建 Session 对齐 C++ 行为。
    """
    if _USE_CURL_CFFI:
        # 每次新建 Session = 对齐 C++ cpr::Post() 的上限 P 临时 Session
        return curl_requests.Session().post(url, json=json_data, headers=headers,
                                            timeout=timeout)  # type: ignore
    else:
        return requests.post(url, json=json_data, headers=headers, timeout=timeout)


class GameType(IntEnum):
    """
    游戏类型 → API 端点映射

    ┌───────────────┬──────┬──────────────────────────────────────────────────┐
    │ 游戏           │ ID   │ API 端点 (fetch / query / scan / confirm)          │
    ├───────────────┼──────┼──────────────────────────────────────────────────┤
    │ 崩坏3          │ 1    │ https://api-sdk.mihoyo.com/bh3_cn/combo/panda/... │
    │ 未定事件簿     │ 2    │ https://hk4e-sdk.mihoyo.com/hk4e_cn/combo/panda/..│
    │ 原神           │ 4    │ https://hk4e-sdk.mihoyo.com/hk4e_cn/combo/panda/..│
    │ 星穹铁道       │ 8    │ https://api-sdk.mihoyo.com/hkrpg_cn/combo/panda/..│
    │ 云游戏         │ 9    │ (未实现)                                          │
    │ 星穹铁道(备)   │ 11   │ (同 ID=8)                                         │
    │ 绝区零         │ 12   │ https://api-sdk.mihoyo.com/nap_cn/combo/panda/... │
    │ 崩坏3(B服)     │ 10000│ https://api-sdk.mihoyo.com/bh3_cn/combo/panda/... │
    └───────────────┴──────┴──────────────────────────────────────────────────┘

    端点域名规律:
      - hk4e-sdk.mihoyo.com  → 自生成二维码 (fetch + query)，仅 app_id=4 (原神) 及 app_id=2
      - api-sdk.mihoyo.com    → 游戏内二维码 (scan + confirm)，所有游戏
      - api-takumi.mihoyo.com → 通行证 token 交换 (stoken/game_token)
      - passport-api.mihoyo.com → 短信登录

    WAF 风控强度: app_id=1(高) > app_id=4(中) > app_id=2(低)
    """
    UNKNOW = 0
    Honkai3 = 1        # 崩坏3 → api-sdk/bh3_cn
    TearsOfThemis = 2  # 未定事件簿 → hk4e-sdk/hk4e_cn (WAF 最宽松)
    Genshin = 4        # 原神 → hk4e-sdk/hk4e_cn (fetch/query), api-sdk/hk4e_cn (scan/confirm)
    HonkaiStarRail = 8 # 星穹铁道 → api-sdk/hkrpg_cn
    CloudGame = 9      # 云游戏 (未实现端点)
    PJSH = 11          # 崩坏：星穹铁道 (备选ID)
    ZenlessZoneZero = 12  # 绝区零 → api-sdk/nap_cn
    Honkai3_BiliBili = 10000  # 崩坏3 BiliBili服 → api-sdk/bh3_cn (带 B站签名)


class ServerType(IntEnum):
    """服务器类型"""
    Official = 1   # 官服
    BiliBili = 2  # BiliBili服


class ScanRet(IntEnum):
    """扫描结果"""
    UNKNOW = 0
    SUCCESS = 1
    FAILURE_1 = 3  # 扫码失败
    FAILURE_2 = 4  # 确认失败
    LIVESTOP = 5   # 直播停止
    STREAMERROR = 6  # 流错误


class LoginQRCodeState(IntEnum):
    """二维码状态"""
    Init = 0
    Scanned = 1
    Confirmed = 2
    Expired = 3


# ═══════════════════════════════════════════════════════════════════
# API URL 定义 — 各游戏端点全集
# ═══════════════════════════════════════════════════════════════════

API_SDK = "https://api-sdk.mihoyo.com"

# ── 崩坏3 (app_id=1) ──────────────────────────────────────────
# 端点: api-sdk.mihoyo.com/bh3_cn/combo/panda/...
BH3_BASE = f"{API_SDK}/bh3_cn"
BH3_V2_LOGIN = f"{BH3_BASE}/combo/granter/login/v2/login"    # B服 login v2
BH3_QRCODE_SCAN = f"{BH3_BASE}/combo/panda/qrcode/scan"
BH3_QRCODE_CONFIRM = f"{BH3_BASE}/combo/panda/qrcode/confirm"
BH3_QRCODE_QUERY = f"{BH3_BASE}/combo/panda/qrcode/query"

# ── 原神 (app_id=4) / 未定事件簿 (app_id=2) — 自生成二维码 ────
# 端点: hk4e-sdk.mihoyo.com/hk4e_cn/combo/panda/...
# 用于程序自己生成二维码的 fetch + query 流程
HK4E_SDK_BASE = "https://hk4e-sdk.mihoyo.com/hk4e_cn"
QRCODE_FETCH = f"{HK4E_SDK_BASE}/combo/panda/qrcode/fetch"    # 获取二维码
QRCODE_QUERY = f"{HK4E_SDK_BASE}/combo/panda/qrcode/query"    # 查询状态
QRCODE_SCAN = f"{HK4E_SDK_BASE}/combo/panda/qrcode/scan"
QRCODE_CONFIRM = f"{HK4E_SDK_BASE}/combo/panda/qrcode/confirm"

# ── 原神 (app_id=4) — 游戏内二维码 ─────────────────────────────
# 端点: api-sdk.mihoyo.com/hk4e_cn/combo/panda/...
# scan/confirm/query 必须用同一域名，否则返回 -105
HK4E_API_BASE = f"{API_SDK}/hk4e_cn"
HK4E_QRCODE_SCAN = f"{HK4E_API_BASE}/combo/panda/qrcode/scan"
HK4E_QRCODE_CONFIRM = f"{HK4E_API_BASE}/combo/panda/qrcode/confirm"
HK4E_QRCODE_QUERY = f"{HK4E_API_BASE}/combo/panda/qrcode/query"

# ── 星穹铁道 (app_id=8) ───────────────────────────────────────
# 端点: api-sdk.mihoyo.com/hkrpg_cn/combo/panda/...
HKRPG_SDK_BASE = f"{API_SDK}/hkrpg_cn"
HKRPG_QRCODE_QUERY = f"{HKRPG_SDK_BASE}/combo/panda/qrcode/query"
HKRPG_QRCODE_SCAN = f"{HKRPG_SDK_BASE}/combo/panda/qrcode/scan"
HKRPG_QRCODE_CONFIRM = f"{HKRPG_SDK_BASE}/combo/panda/qrcode/confirm"

# ── 绝区零 (app_id=12) ────────────────────────────────────────
# 端点: api-sdk.mihoyo.com/nap_cn/combo/panda/...
NAP_SDK_BASE = f"{API_SDK}/nap_cn"
NAP_QRCODE_QUERY = f"{NAP_SDK_BASE}/combo/panda/qrcode/query"
NAP_QRCODE_SCAN = f"{NAP_SDK_BASE}/combo/panda/qrcode/scan"
NAP_QRCODE_CONFIRM = f"{NAP_SDK_BASE}/combo/panda/qrcode/confirm"

# ── 通行证 / 账户 API ──────────────────────────────────────────
# 端点: api-takumi.mihoyo.com (token 交换, 与游戏无关)
TAKUMI_BASE = "https://api-takumi.mihoyo.com"
GAME_TOKEN = f"{TAKUMI_BASE}/auth/api/getGameToken"
GAME_TOKEN_STOKEN = f"{TAKUMI_BASE}/account/ma-cn-session/app/getTokenByGameToken"
MULTI_TOKEN = f"{TAKUMI_BASE}/auth/api/getMultiTokenByLoginTicket"

# ── 短信登录 ───────────────────────────────────────────────────
# 端点: passport-api.mihoyo.com
# 新版API: createLoginCaptcha(发送验证码) / loginByMobileCaptcha(验证登录)
PASSPORT_BASE = "https://passport-api.mihoyo.com"
SMS_CREATE = f"{PASSPORT_BASE}/account/ma-cn-verifier/verifier/createLoginCaptcha"
SMS_LOGIN = f"{PASSPORT_BASE}/account/ma-cn-passport/app/loginByMobileCaptcha"

# RSA 公钥拉取 URL（尝试多个已知端点）
RSA_KEY_URLS = [
    f"{PASSPORT_BASE}/account/ma-cn-passport/app/getRSAKey",
    f"{PASSPORT_BASE}/account/ma-cn-passport/app/get_by_rsa_key",
    f"{PASSPORT_BASE}/account/ma-cn-passport/web/rsa_public_key",
]

# ── 用户信息 ───────────────────────────────────────────────────
# 端点: bbs-api.miyoushe.com (米游社社区 API)
MYS_BASE = "https://bbs-api.miyoushe.com"
USER_INFO = f"{MYS_BASE}/user/api/getUserFullInfo"

# ── 常量 ───────────────────────────────────────────────────────

# 短信发送频率限制
_last_sms_send_time = 0
SMS_COOLDOWN_SECONDS = 60  # 发送间隔至少60秒

# DS 签名盐值
SALT_X6 = "t0qEgfub6cvueAPgR5m9aQWWVciEer7v"

# 设备ID (每次启动生成)
import uuid
DEVICE_ID = str(uuid.uuid4())
# 设备指纹（模拟固定值，对齐游戏客户端）
DEVICE_FP = "38d814469b1e4"


def get_sms_request_headers(lifecycle_id: str = "") -> Dict[str, str]:
    """获取短信登录专用请求头（对齐游戏客户端风格，无DS签名）"""
    if not lifecycle_id:
        lifecycle_id = str(uuid.uuid4())
    return {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "x-rpc-app_id": "c76ync6mutq8",
        "x-rpc-channel_id": "1",
        "x-rpc-channel_version": "2.49.0.189",
        "x-rpc-client_type": "3",
        "x-rpc-device_fp": DEVICE_FP,
        "x-rpc-device_id": DEVICE_ID,
        "x-rpc-device_model": "8BAB",
        "x-rpc-device_name": "LAPTOP-T17POR1K",
        "x-rpc-game_biz": "hk4e_cn",
        "x-rpc-language": "zh-cn",
        "x-rpc-lifecycle_id": lifecycle_id,
        "x-rpc-mdk_version": "2.49.0.189",
        "x-rpc-sdk_version": "2.49.0.189",
        "x-rpc-sys_version": "Windows%2011",
    }


def create_uuid4() -> str:
    """生成UUID4"""
    return str(uuid.uuid4())


def md5(text: str) -> str:
    """MD5哈希"""
    return hashlib.md5(text.encode()).hexdigest()


def hmac_sha256(key: str, message: str) -> str:
    """HMAC-SHA256"""
    import hmac
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def generate_ds(body: str = "", query: str = "") -> str:
    """生成DS签名"""
    t = int(time.time())
    r = random.randint(100001, 200000)
    m = f"salt={SALT_X6}&t={t}&r={r}&b={body}&q={query}"
    return f"{t},{r},{md5(m)}"


def get_request_headers() -> Dict[str, str]:
    """获取请求头"""
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) miHoYoBBS/2.76.1",
        "Accept": "application/json",
        "x-rpc-app_id": "bll8iq97cem8",
        "x-rpc-app_version": "2.76.1",
        "x-rpc-channel": "mihoyo",
        "x-rpc-client_type": "2",
        "x-rpc-device_id": DEVICE_ID,
        "x-rpc-device_name": "",
        "x-rpc-game_biz": "bbs_cn",
        "x-rpc-sdk_version": "2.16.0",
    }


# RSA 公钥缓存
_rsa_key_cache: Optional[str] = None
_rsa_key_expiry: float = 0  # 缓存过期时间


def get_rsa_public_key() -> bytes:
    """获取RSA公钥 - 优先从服务器拉取最新公钥，失败则使用本地硬编码公钥"""
    global _rsa_key_cache, _rsa_key_expiry
    
    # 缓存未过期时直接返回
    if _rsa_key_cache and time.time() < _rsa_key_expiry:
        return _rsa_key_cache.encode()
    
    # 尝试从多个已知端点拉取最新公钥
    for key_url in RSA_KEY_URLS:
        try:
            import requests as _req
            resp = _req.get(key_url, timeout=5)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    pub_key = data.get("data", {}).get("public_key") or data.get("data", {}).get("rsa_key") or data.get("rsa_key") or data.get("public_key")
                    if pub_key:
                        _rsa_key_cache = f"-----BEGIN PUBLIC KEY-----\n{pub_key}\n-----END PUBLIC KEY-----"
                        _rsa_key_expiry = time.time() + 3600
                        api_log(f"[rsa_key] 已从 {key_url} 获取最新RSA公钥，缓存1小时", LogLevel.INFO)
                        return _rsa_key_cache.encode()
                except Exception:
                    # 可能是HTML或其它格式
                    text = resp.text
                    # 尝试从HTML中提取 public_key
                    import re
                    m = re.search(r'"public_key"\s*:\s*"([^"]+)"', text)
                    if m:
                        pub_key = m.group(1)
                        _rsa_key_cache = f"-----BEGIN PUBLIC KEY-----\n{pub_key}\n-----END PUBLIC KEY-----"
                        _rsa_key_expiry = time.time() + 3600
                        api_log(f"[rsa_key] 已从 {key_url} HTML中提取RSA公钥，缓存1小时", LogLevel.INFO)
                        return _rsa_key_cache.encode()
                    api_log(f"[rsa_key] {key_url} 返回非JSON内容", LogLevel.DEBUG)
            else:
                api_log(f"[rsa_key] {key_url} HTTP {resp.status_code}", LogLevel.DEBUG)
        except Exception as e:
            api_log(f"[rsa_key] {key_url} 异常: {e}", LogLevel.DEBUG)
    
    api_log(f"[rsa_key] 所有URL均无法获取公钥，使用硬编码公钥", LogLevel.WARN)
    
    # 回退：使用硬编码公钥
    public_key_pem = b"""-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDDvekdPMHN3AYhm/vktJT+YJr7
cI5DcsNKqdsx5DZX0gDuWFuIjzdwButrIYPNmRJ1G8ybDIF7oDW2eEpm5sMbL9zs
9ExXCdvqrn51qELbqj0XxtMTIpaCHFSI50PfPpTFV9Xt/hmyVwokoOXFlAEgCn+Q
CgGs52bFoYMtyi+xEQIDAQAB
-----END PUBLIC KEY-----"""
    return public_key_pem


def rsa_encrypt(data: str) -> str:
    """RSA加密"""
    public_key = serialization.load_pem_public_key(
        get_rsa_public_key(),
        backend=default_backend()
    )
    encrypted = public_key.encrypt(
        data.encode(),
        padding.PKCS1v15()
    )
    return base64.b64encode(encrypted).decode()


class MhyApi:
    """米哈游API调用类"""
    
    def __init__(self):
        self.session = requests.Session()
        self.device_id = DEVICE_ID
        self.last_ticket = ""
        self.game_type = GameType.Genshin
        self.server_type = ServerType.Official
    
    def set_game_type(self, game_type: GameType):
        """设置游戏类型"""
        self.game_type = game_type
    
    def set_server_type(self, server_type: ServerType):
        """设置服务器类型"""
        self.server_type = server_type
    
    def fetch_qrcode_url(self) -> Tuple[str, str]:
        """
        获取二维码URL（对齐 C++ GetLoginQrcodeUrl — 仅 Content-Type 头，无状态请求）
        Returns: (qrcode_url, ticket)

        ticket 提取策略：
        - 对齐 C++: ticket = URL 末尾 24 字符
          C++ WindowLogin.cpp: string_view ticket(str.data() + str.size() - 24, 24);
        """
        # 对齐 C++: app_id = static_cast<int>(loginType) = GameType::TearsOfThemis = 2
        # app_id=1/4 均在 ~5 次 query 后触发 -3503；仅 app_id=2 WAF 阈值足够宽松
        app_id = 2
        data = {
            "app_id": app_id,
            "device": self.device_id
        }
        # C++ fetch_qrcode 仅发 Content-Type，不带 User-Agent / x-rpc-* 头
        headers = {"Content-Type": "application/json"}

        try:
            resp = _safe_post(QRCODE_FETCH, json_data=data, headers=headers)
            result = resp.json()
            qr_log(f"[fetch_qrcode_url] response: {result}", LogLevel.DEBUG)

            if result.get("retcode", -1) == 0:
                qrcode_url = result["data"]["url"]
                qr_log(f"[fetch_qrcode_url] QR URL: {qrcode_url}", LogLevel.DEBUG)

                # 对齐 C++: URL 末尾 24 字符为 ticket
                if len(qrcode_url) >= 24:
                    ticket = qrcode_url[-24:]
                    qr_log(f"[fetch_qrcode_url] ticket(by [-24:]): {ticket}", LogLevel.DEBUG)
                else:
                    ticket = ""
                    qr_log(f"[fetch_qrcode_url] 无法提取ticket! URL={qrcode_url}", LogLevel.WARN)

                return qrcode_url, ticket
            else:
                qr_log(f"获取二维码失败: {result}", LogLevel.WARN)
                return "", ""
        except Exception as e:
            qr_log(f"请求异常: {e}", LogLevel.ERROR)
            return "", ""
    
    def query_qrcode_state(self, ticket: str, biz_key: str = "") -> Tuple[LoginQRCodeState, str, str]:
        """
        查询二维码状态（用于程序自己生成的二维码）
        Returns: (state, uid, token)
        
        与 fetch 的 app_id 保持一致。
        """
        # 对齐 C++: app_id = static_cast<int>(loginType) = GameType::TearsOfThemis = 2
        # app_id=1/4 均在 ~5 次 query 后触发 -3503；仅 app_id=2 WAF 阈值足够宽松
        app_id = 2
        return self._query_qrcode_state_impl(ticket, app_id, QRCODE_QUERY, biz_key)

    def query_game_qrcode_state(self, ticket: str, app_id: int, biz_key: str = "") -> Tuple[LoginQRCodeState, str, str]:
        """
        查询游戏内二维码状态
        Returns: (state, uid, token)
        
        **注意**: 游戏内二维码 (app_id!=1) 的 query 端点不工作（返回 -105）。
        C++ 中 GetQRCodeState 仅用于自生成二维码 (app_id=1) 的 fetch→query 轮询。
        游戏内二维码使用 scan→confirm 流程，无轮询。
        
        API 地址:
        - app_id=1  (崩坏3): BH3_QRCODE_QUERY
        - app_id=4  (原神): HK4E_QRCODE_QUERY (api-sdk, 但返回-105)
        - app_id=8  (星铁): HKRPG_QRCODE_QUERY
        - app_id=12 (绝区零): NAP_QRCODE_QUERY
        """
        # 根据 app_id 选择正确的 API URL
        # 参考 C++ ApiDefs.hpp：query 用 hk4e-sdk 域名
        if app_id == 1:  # 崩坏3
            api_url = BH3_QRCODE_QUERY
        elif app_id == 4:  # 原神 - query 用 hk4e-sdk
            api_url = HK4E_QRCODE_QUERY
        elif app_id == 8:  # 星铁
            api_url = HKRPG_QRCODE_QUERY
        elif app_id == 12:  # 绝区零
            api_url = NAP_QRCODE_QUERY
        else:
            api_url = QRCODE_QUERY

        qr_log(f"[query_game_qrcode_state] app_id={app_id}, api_url={api_url}", LogLevel.DEBUG)
        return self._query_qrcode_state_impl(ticket, app_id, api_url, biz_key)

    def _query_qrcode_state_impl(self, ticket: str, app_id: int, api_url: str, biz_key: str = "") -> Tuple[LoginQRCodeState, str, str]:
        """
        内部实现：查询二维码状态（对齐 C++ GetQRCodeState）
        Returns: (state, uid, token)

        C++ MhyApi.hpp GetQRCodeState:
        - 请求体仅 {app_id, device, ticket}，无 biz_key
        - 请求头仅 Content-Type: application/json，无 x-rpc 系列头
        - 无状态 POST，不使用 session
        - retcode != 0 → 直接返回 Expired（无子类型区分）
        - 未知 stat → 返回 Expired
        """
        data = {
            "app_id": app_id,
            "device": self.device_id,
            "ticket": ticket
        }

        # 使用 curl_cffi 模拟 libcurl TLS 指纹，与 C++ 行为一致
        # C++ GetQRCodeState 仅发 Content-Type，不带 User-Agent / x-rpc-* 头
        headers = {"Content-Type": "application/json"}

        qr_log(f"[query_qrcode_state] URL={api_url}, ticket={ticket[:12]}..., app_id={app_id}", LogLevel.DEBUG)

        try:
            resp = _safe_post(api_url, json_data=data, headers=headers)
            result = resp.json()
            qr_log(f"[query_qrcode_state] response: {result}", LogLevel.DEBUG)

            retcode = result.get("retcode", -1)
            # 对齐 C++ MhyApi.hpp: if (retcode != 0) return Expired
            # C++ 把任何非0 retcode（包括 -3503 WAF风控）都当作 Expired，
            # 这样会触发二维码自动刷新，重新获取 ticket 后不再被 WAF 拦截。
            # Python 之前把 -3503 当作 Init 继续轮询 → 同一个 ticket 被 WAF 永久封堵 → 死循环。
            if retcode != 0:
                msg = result.get("message", "")
                qr_log(f"[query_qrcode_state] retcode={retcode} msg={msg} → Expired", LogLevel.WARN)
                return LoginQRCodeState.Expired, "", ""

            # data 可能为 None
            if not result.get("data"):
                qr_log(f"[query_qrcode_state] data is None → Init", LogLevel.DEBUG)
                return LoginQRCodeState.Init, "", ""

            stat = result["data"]["stat"]
            qr_log(f"[query_qrcode_state] stat='{stat}'", LogLevel.DEBUG)

            state_map = {
                "Init": LoginQRCodeState.Init,
                "Scanned": LoginQRCodeState.Scanned,
                "Confirmed": LoginQRCodeState.Confirmed,
            }

            state = state_map.get(stat, LoginQRCodeState.Expired)

            # Confirmed 状态解析 payload 获取 uid/token
            if state == LoginQRCodeState.Confirmed:
                try:
                    payload = json.loads(result["data"]["payload"]["raw"])
                    uid = payload.get("uid", "")
                    token = payload.get("token", "")
                    qr_log(f"[query_qrcode_state] Confirmed! uid={uid}")
                    return state, uid, token
                except Exception as e:
                    qr_log(f"[query_qrcode_state] Confirmed payload解析失败: {e}", LogLevel.ERROR)
                    return LoginQRCodeState.Expired, "", ""

            qr_log(f"[query_qrcode_state] returning state={state.name}", LogLevel.DEBUG)
            return state, "", ""
        except Exception as e:
            qr_log(f"查询二维码状态异常: {e}", LogLevel.WARN)
            # 异常时不返回 Expired，返回 Init 保持轮询（避免网络抖动导致误判）
            return LoginQRCodeState.Init, "", ""
    
    def scan_qrcode(self, ticket: str, app_id: int = 1, biz_key: str = "", url: str = "") -> bool:
        """
        扫码确认（参考 C++ ScanQRLogin）
        
        C++ 中 ScanQRLogin 使用 ApiDefs.hpp 中定义的固定 API URL（api-sdk 域名）。
        C++ 请求体仅含 app_id, device, ticket（无 biz_key）。
        """
        # 如果传入了自定义 URL，优先使用
        if url:
            api_url = url
        else:
            # 根据 app_id 选择正确的 API URL
            if app_id == 1:  # 自生成二维码（与 fetch/query 同一 hk4e-sdk 域名）
                api_url = QRCODE_SCAN
            elif app_id == 4:  # 原神 - 游戏内二维码使用 api-sdk 域名
                api_url = HK4E_QRCODE_SCAN
            elif app_id == 8:  # 星铁
                api_url = HKRPG_QRCODE_SCAN
            elif app_id == 12:  # 绝区零
                api_url = NAP_QRCODE_SCAN
            else:
                api_url = QRCODE_SCAN

        data = {
            "app_id": app_id,
            "device": self.device_id,
            "ticket": ticket
        }
        if biz_key:
            data["biz_key"] = biz_key

        # C++ ScanQRLogin 仅发 Content-Type: application/json，无 User-Agent / x-rpc-* 头
        headers = {"Content-Type": "application/json"}

        try:
            qr_log(f"[scan_qrcode] 发送请求到: {api_url}", LogLevel.DEBUG)
            qr_log(f"[scan_qrcode] 请求数据: {data}", LogLevel.DEBUG)
            # 无状态 POST（C++ 中 scan 不使用 session）
            resp = _safe_post(api_url, json_data=data, headers=headers)
            result = resp.json()
            qr_log(f"[scan_qrcode] response: {result}", LogLevel.DEBUG)
            return result.get("retcode", -1) == 0
        except Exception as e:
            qr_log(f"扫码确认异常: {e}", LogLevel.ERROR)
            return False
    
    def confirm_qrcode(self, ticket: str, uid: str, token: str, app_id: int = 1, biz_key: str = "") -> bool:
        """确认登录"""
        # 根据 app_id 选择正确的 API URL
        if app_id == 1:  # 崩坏3
            api_url = BH3_QRCODE_CONFIRM
        elif app_id == 4:  # 原神 - 游戏内二维码使用 api-sdk 域名
            api_url = HK4E_QRCODE_CONFIRM
        elif app_id == 8:  # 星铁
            api_url = HKRPG_QRCODE_CONFIRM
        elif app_id == 12:  # 绝区零
            api_url = NAP_QRCODE_CONFIRM
        else:
            api_url = QRCODE_CONFIRM
        
        data = {
            "app_id": app_id,
            "device": self.device_id,
            "ticket": ticket,
            "payload": {
                "proto": "Account",
                "raw": json.dumps({"uid": uid, "token": token})
            }
        }
        if biz_key:
            data["biz_key"] = biz_key

        # C++ ConfirmQRLogin 仅发 Content-Type: application/json，无 User-Agent / x-rpc-* 头
        headers = {"Content-Type": "application/json"}

        qr_log(f"[confirm_qrcode] 请求数据: {data}", LogLevel.DEBUG)
        qr_log(f"[confirm_qrcode] 请求URL: {api_url}", LogLevel.DEBUG)

        try:
            # 无状态 POST（与 C++ 一致）
            resp = _safe_post(api_url, json_data=data, headers=headers)
            result = resp.json()
            qr_log(f"[confirm_qrcode] 响应: {result}", LogLevel.DEBUG)
            return result.get("retcode", -1) == 0
        except Exception as e:
            qr_log(f"确认登录异常: {e}", LogLevel.ERROR)
            return False
    
    def get_stoken_by_game_token(self, uid: str, game_token: str, ticket: str = "", biz_key: str = "") -> Tuple[int, str, str]:
        """通过game_token获取stoken。
        
        对应C++ MhyApi.hpp GetStokenByGameToken：
        - 请求体仅含 account_id(int) + game_token，无 device/ticket
        - Header 始终用 x-rpc-game_biz: bbs_cn（QR登录是通行证/BBS流程，不是游戏流程）
        - 无状态HTTP POST，不携带任何cookies
        """
        import requests as req

        data = {
            "account_id": int(uid),
            "game_token": game_token
        }
        # 注意：C++参考代码中请求体只包含这两个字段，不包含 device 或 ticket

        headers = get_request_headers()
        # 关键：不要覆盖 x-rpc-game_biz！C++ 始终使用 "bbs_cn"
        # QR登录是米哈游通行证(BBS)流程，不是 bh3_cn 等游戏流程

        api_log(f"[get_stoken_by_game_token] uid={uid}", LogLevel.DEBUG)
        api_log(f"[get_stoken_by_game_token] request: {json.dumps(data)}", LogLevel.DEBUG)
        api_log(f"[get_stoken_by_game_token] headers.game_biz: {headers.get('x-rpc-game_biz', 'N/A')}", LogLevel.DEBUG)

        try:
            resp = req.post(GAME_TOKEN_STOKEN, json=data, headers=headers, timeout=10)
            result = resp.json()
            api_log(f"[get_stoken_by_game_token] response: {result}", LogLevel.DEBUG)

            retcode = result.get("retcode", -1)
            if retcode == 0:
                mid = result["data"]["user_info"]["mid"]
                stoken = result["data"]["token"]["token"]
                api_log(f"[get_stoken_by_game_token] success!")
                return 0, mid, stoken
            else:
                api_log(f"[get_stoken_by_game_token] retcode={retcode}, msg={result.get('message', '')}", LogLevel.WARN)
                return retcode, "", ""
        except Exception as e:
            api_log(f"[get_stoken_by_game_token] ex: {e}", LogLevel.ERROR)
            return -1, "", ""
    
    def get_game_token_by_stoken(self, stoken: str, mid: str) -> Tuple[int, str]:
        """
        通过stoken获取game_token（参考 C++ GetGameTokenByStoken — 无自定义headers）
        Returns: (retcode, game_token)
        """
        params = {
            "stoken": stoken,
            "mid": mid
        }
        
        # C++ GetGameTokenByStoken 不发送任何自定义 headers，无状态 GET
        try:
            resp = requests.get(GAME_TOKEN, params=params, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            
            if result.get("retcode", -1) == 0:
                return 0, result["data"]["game_token"]
            else:
                return result.get("retcode", -1), ""
        except Exception as e:
            api_log(f"获取game_token异常: {e}", LogLevel.WARN)
            return -1, ""
    
    def get_mys_user_name(self, uid: str) -> str:
        """获取米游社用户名（对齐 C++ getMysUserName — 无自定义headers，无状态GET）"""
        import requests as req

        url = f"{USER_INFO}?uid={uid}"

        # C++ getMysUserName: cpr::Get + {url}?uid={uid}，无任何自定义 headers
        try:
            resp = req.get(url, timeout=10)
            result = resp.json()
            qr_log(f"[get_mys_user_name] response: {result}", LogLevel.DEBUG)

            if result.get("retcode", 0) == 0:
                return result["data"]["user_info"]["nickname"]
            else:
                return ""
        except Exception as e:
            qr_log(f"获取用户名异常: {e}", LogLevel.WARN)
            return ""
    
    # ========== 短信登录 ==========
    
    def send_sms_code(self, phone: str, aigis: str = "") -> Tuple[int, str, Dict[str, Any]]:
        """
        发送短信验证码
        Args:
            phone: 手机号 (如 13800138000 或 +8613800138000)
            aigis: X-Rpc-Aigis 请求头（完成滑块验证后传入，用于重试）
        Returns: (retcode, action_type, extra_data)
        extra_data 可能包含 geetest 验证所需参数 (gt, session_id)
        """
        global _last_sms_send_time
        
        # 非重试请求才检查频率限制（带 aigis 的重试不限制）
        if not aigis:
            current_time = time.time()
            if current_time - _last_sms_send_time < SMS_COOLDOWN_SECONDS:
                remaining = int(SMS_COOLDOWN_SECONDS - (current_time - _last_sms_send_time))
                api_log(f"[send_sms_code] 发送过于频繁，请等待 {remaining} 秒后再试", LogLevel.WARN)
                return -3002, f"发送过于频繁，请等待 {remaining} 秒后再试", {}
            _last_sms_send_time = current_time
        
        import requests as req
        
        # 提取纯手机号（去掉+86前缀）
        clean_phone = phone
        if clean_phone.startswith("+86"):
            clean_phone = clean_phone[3:]
        elif clean_phone.startswith("86"):
            clean_phone = clean_phone[2:]
        
        # RSA加密手机号和区号（新版API两者都需要加密）
        encrypted_phone = self._rsa_encrypt(clean_phone)
        encrypted_area_code = self._rsa_encrypt("+86")
        
        body_data = {
            "area_code": encrypted_area_code,
            "mobile": encrypted_phone
        }
        body_str = json.dumps(body_data, separators=(',', ':'))
        
        # 使用游戏客户端风格请求头（无DS签名）
        lifecycle_id = str(uuid.uuid4())
        headers = get_sms_request_headers(lifecycle_id)
        headers["Content-Length"] = str(len(body_str))
        
        if aigis:
            headers["X-Rpc-Aigis"] = aigis
            api_log(f"[send_sms_code] 携带 Aigis 头重试", LogLevel.DEBUG)
        
        api_log(f"[send_sms_code] 发送请求到: {SMS_CREATE}", LogLevel.DEBUG)
        api_log(f"[send_sms_code] 请求体: {body_str}", LogLevel.DEBUG)
        
        try:
            resp = req.post(SMS_CREATE, data=body_str.encode(), headers=headers, timeout=10)
            result = resp.json()
            api_log(f"[send_sms_code] response: {result}", LogLevel.DEBUG)
            
            retcode = result.get("retcode", -1)
            
            if retcode == 0:
                action_type = result.get("data", {}).get("action_type", "")
                return 0, action_type, {}
            elif retcode == -3101:
                # 需要滑块验证 (GeeTest v4)
                aigis_header = resp.headers.get("X-Rpc-Aigis", "{}")
                try:
                    aigis_data = json.loads(aigis_header)
                except json.JSONDecodeError:
                    aigis_data = {}
                captcha_data_str = aigis_data.get("data", "{}")
                try:
                    captcha_data = json.loads(captcha_data_str)
                except json.JSONDecodeError:
                    captcha_data = {}
                extra = {
                    "session_id": aigis_data.get("session_id", ""),
                    "mmt_type": aigis_data.get("mmt_type", 0),
                    "gt": captcha_data.get("gt", ""),
                    "new_captcha": captcha_data.get("new_captcha", 1),
                    "use_v4": captcha_data.get("use_v4", True),
                }
                return -3101, "", extra
            else:
                return retcode, result.get("message", ""), {}
        except Exception as e:
            api_log(f"[send_sms_code] exception: {e}", LogLevel.ERROR)
            return -1, str(e), {}
    
    def login_by_sms(self, phone: str, captcha: str, action_type: str = "", aigis: str = "") -> Tuple[int, str, str, str]:
        """
        短信验证码登录
        Returns: (retcode, v2_token, uid, mid)
        """
        import requests as req
        
        # 提取纯手机号
        clean_phone = phone
        if clean_phone.startswith("+86"):
            clean_phone = clean_phone[3:]
        elif clean_phone.startswith("86"):
            clean_phone = clean_phone[2:]
        
        # RSA加密手机号和区号（新版API两者都需要加密）
        encrypted_phone = self._rsa_encrypt(clean_phone)
        encrypted_area_code = self._rsa_encrypt("+86")
        
        body_data = {
            "area_code": encrypted_area_code,
            "action_type": action_type,
            "captcha": captcha,
            "mobile": encrypted_phone
        }
        body_str = json.dumps(body_data, separators=(',', ':'))
        
        # 使用游戏客户端风格请求头（无DS签名）
        lifecycle_id = str(uuid.uuid4())
        headers = get_sms_request_headers(lifecycle_id)
        headers["Content-Length"] = str(len(body_str))
        if aigis:
            headers["X-Rpc-Aigis"] = aigis
        
        api_log(f"[login_by_sms] 发送请求到: {SMS_LOGIN}", LogLevel.DEBUG)
        api_log(f"[login_by_sms] 请求体: {body_str}", LogLevel.DEBUG)
        
        try:
            resp = req.post(SMS_LOGIN, data=body_str.encode(), headers=headers, timeout=10)
            result = resp.json()
            api_log(f"[login_by_sms] response: {result}", LogLevel.DEBUG)
            
            retcode = result.get("retcode", -1)
            
            if retcode == 0:
                v2_token = result["data"]["token"]["token"]
                uid = str(result["data"]["user_info"]["aid"])
                mid = result["data"]["user_info"]["mid"]
                return 0, v2_token, uid, mid
            elif retcode == -3205:
                return -3205, "", "", ""
            else:
                return retcode, "", "", ""
        except Exception as e:
            api_log(f"[login_by_sms] exception: {e}", LogLevel.ERROR)
            return -1, "", "", ""
    
    def _rsa_encrypt(self, data: str) -> str:
        """RSA加密（复用模块级函数）"""
        return rsa_encrypt(data)
    
    # ========== 崩坏3 BiliBili 专用 ==========
    
    def bh3_external_login(self, uid: str, access_key: str) -> Tuple[int, str, str, str]:
        """
        崩坏3 BiliBili 外部登录
        Returns: (retcode, open_id, combo_token, combo_id)
        """
        body_data = json.dumps({
            "access_key": access_key,
            "uid": int(uid)
        })
        
        body = {
            "device": "0000000000000000",
            "app_id": 1,
            "channel_id": 14,
            "data": body_data
        }
        
        # 签名
        param_str = "&".join([f"{k}={v}" for k, v in body.items() if k != "sign"])
        sign_key = "0ebc517adb1b62c6b408df153331f9aa"
        body["sign"] = hmac_sha256(sign_key, param_str)
        
        headers = {
            "Content-Type": "application/json"
        }
        
        try:
            resp = requests.post(BH3_V2_LOGIN, json=body, headers=headers, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            
            if result.get("retcode", -1) == 0:
                return (
                    0,
                    result["data"]["open_id"],
                    result["data"]["combo_token"],
                    result["data"]["combo_id"]
                )
            else:
                return result.get("retcode", -1), "", "", ""
        except Exception as e:
            api_log(f"BH3外部登录异常: {e}", LogLevel.ERROR)
            return -1, "", "", ""
    
    def bh3_qrcode_scan(self, ticket: str) -> bool:
        """崩坏3 扫码"""
        body = {
            "app_id": "1",
            "device": "0000000000000000",
            "ticket": ticket,
            "ts": int(time.time())
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        try:
            resp = requests.post(BH3_QRCODE_SCAN, json=body, headers=headers, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            return result.get("retcode", -1) == 0
        except Exception as e:
            qr_log(f"BH3扫码异常: {e}", LogLevel.ERROR)
            return False
    
    def bh3_qrcode_confirm(self, ticket: str, uid: str, access_key: str, name: str) -> ScanRet:
        """崩坏3 确认登录"""
        code, open_id, combo_token, combo_id = self.bh3_external_login(uid, access_key)
        
        if code != 0:
            return ScanRet.FAILURE_2
        
        raw = {
            "heartbeat": False,
            "open_id": open_id,
            "device_id": "0000000000000000",
            "app_id": "1",
            "channel_id": "14",
            "combo_token": combo_token,
            "asterisk_name": name,
            "combo_id": combo_id,
            "account_type": "2"
        }
        
        ext = {
            "data": {
                "accountType": "2",
                "accountID": "",
                "c": open_id,
                "accountToken": combo_token,
                "dispatch": "https://sg-hs4-api.hovipatch.net"
            }
        }
        
        post_body = {
            "device": "0000000000000000",
            "app_id": 1,
            "ts": int(time.time()),
            "ticket": ticket,
            "payload": {
                "proto": "Combo",
                "raw": json.dumps(raw),
                "ext": json.dumps(ext)
            }
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        try:
            resp = requests.post(BH3_QRCODE_CONFIRM, json=post_body, headers=headers, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            
            if result.get("retcode", -1) == 0:
                return ScanRet.SUCCESS
            else:
                return ScanRet.FAILURE_2
        except Exception as e:
            qr_log(f"BH3确认登录异常: {e}", LogLevel.ERROR)
            return ScanRet.FAILURE_2
    
    def parse_qrcode_url(self, url: str) -> Tuple[str, str]:
        """
        解析二维码URL，提取ticket和game_type
        Returns: (ticket, game_type_prefix)
        """
        try:
            # URL格式: https://hk4e-sdk.mihoyo.com/...ticket=xxx...
            if "ticket=" in url:
                ticket = url.split("ticket=")[-1][:24]  # 取ticket
                
                # 判断游戏类型
                if "hkrpg" in url or "SR" in url:
                    return ticket, "hkrpg"
                elif "zzz" in url or "PJSH" in url:
                    return ticket, "zzz"
                elif "bh3" in url:
                    return ticket, "bh3"
                elif "genshin" in url or "hk4e" in url:
                    return ticket, "genshin"
                
                return ticket, ""
            return "", ""
        except Exception as e:
            api_log(f"解析二维码URL异常: {e}", LogLevel.WARN)
            return "", ""


def get_game_type_from_url(url: str) -> Tuple[GameType, int]:
    """
    根据URL offset 79处的3个字符判断游戏类型
    C++项目逻辑:
      "8F3" -> 崩坏3   (app_id=1)
      "9E&" -> 原神     (app_id=4)
      "8F%" -> 星穹铁道 (app_id=8)
      "%BA" -> 绝区零   (app_id=12)
    Returns: (GameType, app_id)
    """
    if len(url) < 82:
        return GameType.UNKNOW, 0

    # URL offset 79 处取 3 个字符
    offset_79 = url[79:82]

    game_mappings = {
        "8F3": (GameType.Honkai3, 1),           # 崩坏3
        "9E&": (GameType.Genshin, 4),           # 原神
        "8F%": (GameType.HonkaiStarRail, 8),   # 星穹铁道
        "%BA": (GameType.ZenlessZoneZero, 12), # 绝区零
    }

    if offset_79 in game_mappings:
        return game_mappings[offset_79]

    # 回退：根据URL关键词判断
    if "hkrpg" in url or "SR" in url or "StarRail" in url:
        return GameType.HonkaiStarRail, 8
    elif "zzz" in url or "nap" in url.lower() or "Zenless" in url:
        return GameType.ZenlessZoneZero, 12
    elif "bh3" in url.lower() or "honkai3" in url.lower():
        return GameType.Honkai3, 1
    elif "genshin" in url or "hk4e" in url:
        return GameType.Genshin, 4

    return GameType.UNKNOW, 0
