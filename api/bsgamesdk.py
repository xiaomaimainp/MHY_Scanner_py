"""
B站SDK模块
实现B站崩坏3登录相关功能
参考 C++ BSGameSDK.hpp:
  - BSGameSDK::BH3::LoginByPassWord     (账号密码+极验)
  - BSGameSDK::BH3::CaptchaCaptcha      (获取极验参数)
  - BSGameSDK::BH3::GetUserInfo         (验证access_key)
"""
import json
import time
import hashlib
import traceback
import urllib.parse
from typing import Tuple, Dict, Any

# 使用 api 模块的公共函数（避免重复定义）
from .api import ServerType, rsa_encrypt
from core.logger import bsgsdk_log, error, LogLevel

# B站API URL
BILI_BASE = "https://line1-sdk-center-login-sh.biligame.net"
BILI_USER_INFO = f"{BILI_BASE}/api/client/user.info"
BILI_LOGIN = f"{BILI_BASE}/api/client/login"
BILI_RSA_KEY = f"{BILI_BASE}/api/client/rsa"
BILI_CAPTCHA = f"{BILI_BASE}/api/client/start_captcha"

# 请求头（与 C++ BSGameSDK.hpp detail::headers 一致）
_BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 BSGameSDK",
    "Content-Type": "application/x-www-form-urlencoded",
    "Host": "line1-sdk-center-login-sh.biligame.net",
}

# B站SDK签名密钥（C++ BSGameSDK.hpp）
_BILI_SIGN_KEY = "dbf8f1b4496f430b8a3c0f436a35b931"

# 预设参数（与 C++ BSGameSDK.hpp detail::rsaParam / loginParam / captchaParam 一致）
_BASE_PARAMS = {
    "operators": "5",
    "merchant_id": "590",
    "isRoot": "0",
    "domain_switch_count": "0",
    "sdk_type": "1",
    "sdk_log_type": "1",
    "support_abis": "x86,armeabi-v7a,armeabi",
    "access_key": "",
    "sdk_ver": "3.4.2",
    "oaid": "",
    "dp": "1280 * 720",
    "original_domain": "",
    "imei": "",
    "version": "1",
    "udid": "XXA31CBAB6CBA63E432E087B58411A213BFB7",
    "apk_sign": "4502a02a00395dec05a4134ad593224d",
    "platform_type": "3",
    "old_buvid": "XZA2FA4AC240F665E2F27F603ABF98C615C29",
    "android_id": "84567e2dda72d1d4",
    "fingerprint": "",
    "mac": "08:00:27:53:DD:12",
    "server_id": "378",
    "domain": "line1-sdk-center-login-sh.biligame.net",
    "app_id": "180",
    "version_code": "510",
    "net": "4",
    "pf_ver": "12",
    "cur_buvid": "XZA2FA4AC240F665E2F27F603ABF98C615C29",
    "c": "1",
    "brand": "Android",
    "channel_id": "1",
    "uid": "",
    "game_id": "180",
    "ver": "6.1.0",
    "model": "MuMu",
}


def _set_sign(data: dict) -> str:
    """B站SDK签名，与 C++ BSGameSDK::detail::SetSign 一致。

    返回值: URL 编码的 body 字符串 (含 sign)
    """
    import http.client
    timestamp = str(int(time.time() * 1000))
    data["timestamp"] = timestamp
    data["client_timestamp"] = timestamp

    body_parts = []
    sign_parts = []

    for key, value in data.items():
        if isinstance(value, (dict, list)):
            value_str = json.dumps(value, separators=(',', ':'))
        else:
            value_str = str(value)

        if key == "pwd":
            # pwd 需要 URL 编码（C++ urlEncode）
            body_parts.append(f"{key}={urllib.parse.quote(value_str, safe='')}")
        else:
            body_parts.append(f"{key}={value_str}")
        body_parts.append("&")
        sign_parts.append(value_str)

    sign_input = "".join(sign_parts) + _BILI_SIGN_KEY
    sign = hashlib.md5(sign_input.encode()).hexdigest()

    body = "".join(body_parts) + f"sign={sign}"
    return body


class BSGameSDK:
    """B站SDK登录类"""

    def __init__(self):
        self._session = __import__('requests').Session()

    # ---- RSA 加密 ----

    def get_encrypted_pwd(self, password: str) -> Tuple[bool, str, str]:
        """获取加密后的密码（与 C++ GetEncryptedPwd 一致）。

        流程: request RSA key -> encrypt(hash + password)

        Returns: (success, encrypted_pwd, hash_value)
        """
        import requests as req
        data = {**_BASE_PARAMS}
        # rsaParam 不需要 uid/pwd/challenge
        for k in ("uid", "pwd", "challenge", "validate",
                   "seccode", "gt_user_id", "user_id", "captcha_type"):
            data.pop(k, None)
        body = _set_sign(data)

        try:
            resp = req.post(BILI_RSA_KEY, data=body, headers=_BILI_HEADERS, timeout=10)
            rsa_info = resp.json()
            public_key = rsa_info.get("rsa_key", "")
            hash_val = rsa_info.get("hash", "")
            if not public_key:
                return False, "", ""
            encrypted = rsa_encrypt(hash_val + password)
            if not encrypted:
                return False, "", ""
            return True, encrypted, hash_val
        except Exception as e:
            error(f"RSA加密失败: {e}\n{traceback.format_exc()}")
            return False, "", ""

    # ---- 登录 ----

    def login(self, account: str, password: str,
              gt_user: str = "", challenge: str = "", validate: str = "") -> Tuple[int, str, Dict[str, Any]]:
        """B站登录（账号+密码，可选极验验证）。

        与 C++ BSGameSDK::BH3::LoginByPassWord 一致。

        Args:
            account: B站账号
            password: 明文密码
            gt_user: 极验 gt_user_id / session_id
            challenge: 极验 challenge
            validate: 极验 validate

        Returns: (code, message, data)
            data: {uid, access_key, uname} (code==0)
        """
        import requests as req

        # 1) 获取加密密码
        ok, encrypted_pwd, _ = self.get_encrypted_pwd(password)
        if not ok:
            return -1, "获取加密密钥失败", {}

        # 2) 构建请求参数（与 C++ loginParam 一致）
        data = {**_BASE_PARAMS}
        data["access_key"] = ""
        data["gt_user_id"] = gt_user
        data["uid"] = ""
        data["challenge"] = challenge
        data["user_id"] = account
        data["validate"] = validate
        if validate:
            data["seccode"] = validate + "|jordan"
        else:
            data["seccode"] = ""
        data["pwd"] = encrypted_pwd
        data["captcha_type"] = "1"

        body = _set_sign(data)

        try:
            resp = req.post(BILI_LOGIN, data=body, headers=_BILI_HEADERS, timeout=10)
            login_info = resp.json()
            code = login_info.get("code", -1)

            if code == 200000 or code != 0:
                message = login_info.get("message", "登录错误")
                return code, message, {}

            uid = str(login_info.get("uid", ""))
            access_key = login_info.get("access_key", "")

            # 3) 获取用户名
            _, uname = self.get_user_info(access_key)
            return 0, "", {"uid": uid, "access_key": access_key, "nickname": uname}
        except Exception as e:
            error(f"登录失败: {e}\n{traceback.format_exc()}")
            return -1, str(e), {}

    # ---- 用户信息 ----

    def get_user_info(self, access_key: str) -> Tuple[int, str]:
        """获取B站用户信息（与 C++ BSGameSDK::BH3::GetUserInfo 一致）。

        Returns: (code, uname)
        """
        import requests as req
        data = {**_BASE_PARAMS}
        data["uid"] = ""
        data["access_key"] = access_key
        body = _set_sign(data)

        try:
            resp = req.post(BILI_USER_INFO, data=body, headers=_BILI_HEADERS, timeout=10)
            info = resp.json()
            code = info.get("code", -1)
            if code != 0:
                return code, ""
            return 0, info.get("uname", "")
        except Exception as e:
            error(f"用户信息失败: {e}\n{traceback.format_exc()}")
            return -1, ""

    # ---- 极验验证 ----

    def captcha(self) -> Dict[str, Any]:
        """获取极验验证码参数（与 C++ BSGameSDK::BH3::CaptchaCaptcha 一致）。

        Returns: {gt, challenge, session_id, GeeTestType}
        """
        import requests as req
        data = {**_BASE_PARAMS}
        # captchaParam 不需要 uid/pwd 等
        for k in ("uid", "pwd", "challenge", "validate",
                   "seccode", "gt_user_id", "user_id", "captcha_type"):
            data.pop(k, None)
        data["imei"] = "227656364311444"
        body = _set_sign(data)

        try:
            resp = req.post(BILI_CAPTCHA, data=body, headers=_BILI_HEADERS, timeout=10)
            captcha = resp.json()
            if captcha.get("code") != 0:
                bsgsdk_log(f"captcha 失败: {captcha}", LogLevel.WARN)
                return {}
            return {
                "gt": captcha.get("gt", ""),
                "challenge": captcha.get("challenge", ""),
                "session_id": captcha.get("gt_user_id", ""),
                "GeeTestType": ServerType.BiliBili,
            }
        except Exception as e:
            error(f"极验获取失败: {e}\n{traceback.format_exc()}")
            return {}
