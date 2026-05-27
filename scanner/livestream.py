"""
直播流链接获取模块
支持B站和抖音直播平台
"""
import json
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

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.real_room_id = ""

    def _get_stream_url(self, params: dict) -> str:
        """
        从 getRoomPlayInfo 响应中提取拼接流URL
        """
        url = f"{self.API_BASE}/xlive/web-room/v2/index/getRoomPlayInfo"
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code != 200 or not resp.text:
                return ""

            play_info = resp.json()
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
            except (KeyError, IndexError, TypeError):
                return ""

            base_url = codec.get("base_url", "")
            url_info_list = codec.get("url_info", [])
            if not url_info_list:
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
            # ---- 第1步: room_init 获取房间初始化信息 ----
            room_init_url = f"{self.API_BASE}/room/v1/Room/room_init"
            resp = requests.get(room_init_url, params={"id": self.room_id}, timeout=10)

            if resp.status_code != 200 or not resp.text:
                info.status = LiveStreamStatus.Error
                return info

            room_info = resp.json()
            code = room_info.get("code", -1)
            bili_log(f"room_init code={code}", LogLevel.DEBUG)

            # code == 60004 表示直播间不存在
            if code == 60004:
                info.status = LiveStreamStatus.Absent
                return info

            if code != 0:
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
            if link:
                info.status = LiveStreamStatus.Normal
                info.link = link
            else:
                info.status = LiveStreamStatus.Error

            return info

        except json.JSONDecodeError:
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
            resp = requests.get(url, params=params, timeout=10)
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

    # 硬编码的 Cookie（包含完整认证令牌，绕过反爬签名校验）
    _HARDCODED_COOKIE = (
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

    def __init__(self, room_id: str):
        self.room_id = room_id

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
                "Cookie": self._HARDCODED_COOKIE,
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
