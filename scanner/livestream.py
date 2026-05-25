"""
直播流链接获取模块
支持B站和抖音直播平台
"""
import json
import re
import traceback
import requests
from enum import IntEnum
from typing import Tuple, Optional, Dict, Any
import subprocess
from core.logger import bili_log, douyin_log, error, debug, LogLevel


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
    """B站直播获取"""
    
    API_BASE = "https://api.live.bilibili.com"
    
    def __init__(self, room_id: str):
        self.room_id = room_id
        self.real_room_id = ""
    
    def get_real_room_id(self) -> str:
        """获取真实房间号"""
        url = f"{self.API_BASE}/room/v1/Room/room_init"
        params = {"id": self.room_id}
        
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            
            if result.get("code") == 0:
                self.real_room_id = str(result["data"]["room_id"])
                return self.real_room_id
            else:
                bili_log(f"room_init 返回: code={result.get('code')}, msg={result.get('msg', 'N/A')}", LogLevel.WARN)
                return ""
        except Exception as e:
            error(f"获取B站真实房间号失败: {e}\n{traceback.format_exc()}")
            return ""
    
    def get_live_stream_url(self) -> Tuple[LiveStreamStatus, str]:
        """
        获取B站直播流地址
        
        Returns:
            (状态, 流URL)
        """
        if not self.real_room_id:
            self.get_real_room_id()
        
        if not self.real_room_id:
            return LiveStreamStatus.Absent, ""
        
        url = f"{self.API_BASE}/xlive/web-room/v2/index/getRoomPlayInfo"
        params = {
            "room_id": self.real_room_id,
            "play_url": 1,
            "mask": 1,
            "pt_options": "h265%2Ch264",
            "force_url": 1,
            "stream_protocol": "hls",
            "protocol": "0,1",
            "format": "0,1,2",
            "codec": "0,1,2"
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": f"https://live.bilibili.com/{self.real_room_id}"
        }
        
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            
            if result.get("code") != 0:
                bili_log(f"getRoomPlayInfo 返回: code={result.get('code')}, msg={result.get('message', 'N/A')}", LogLevel.WARN)
                if result.get("code") == -400 or result.get("code") == 1:
                    return LiveStreamStatus.NotLive, ""
                return LiveStreamStatus.Error, ""
            
            data = result.get("data", {})
            
            # 检查是否开播
            live_status = data.get("live_status")
            bili_log(f"live_status={live_status}")
            
            if live_status != 1:
                return LiveStreamStatus.NotLive, ""
            
            # 获取流URL - 尝试多种方式
            # 方式1: durl列表
            play_url_data = data.get("play_url", {})
            durl = play_url_data.get("durl", [])
            
            bili_log(f"durl列表长度: {len(durl)}", LogLevel.DEBUG)
            
            if durl:
                for i, stream in enumerate(durl):
                    stream_url = stream.get("url", "")
                    if stream_url:
                        return LiveStreamStatus.Normal, stream_url
            
            # 方式2: 流地址列表 (不同格式)
            stream_list = data.get("stream_url", [])
            if stream_list:
                for stream in stream_list:
                    if isinstance(stream, dict):
                        url_val = stream.get("url") or stream.get("main_url")
                        if url_val:
                            return LiveStreamStatus.Normal, url_val
            
            # 方式3: live_play_url
            live_play_url = data.get("live_play_url", "")
            if live_play_url:
                return LiveStreamStatus.Normal, live_play_url
            
            bili_log(f"play_url_data keys: {list(play_url_data.keys()) if play_url_data else 'None'}", LogLevel.DEBUG)
            bili_log(f"data keys: {list(data.keys())}", LogLevel.DEBUG)
            return LiveStreamStatus.Error, ""
            
        except Exception as e:
            error(f"获取B站直播流失败: {e}\n{traceback.format_exc()}")
            return LiveStreamStatus.Error, ""
    
    def get_room_info(self) -> Dict[str, Any]:
        """获取直播间信息"""
        if not self.real_room_id:
            self.get_real_room_id()
        
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
    
    def get_live_stream_info(self) -> LiveStreamInfo:
        """获取完整的直播流信息"""
        info = LiveStreamInfo()
        info.room_id = self.room_id
        
        # 获取真实房间号
        self.get_real_room_id()
        
        if not self.real_room_id:
            info.status = LiveStreamStatus.Absent
            return info
        
        info.room_id = self.real_room_id
        
        # 获取直播间信息
        room_info = self.get_room_info()
        info.title = room_info.get("title", "")
        info.uname = room_info.get("uname", "")
        
        # 获取流地址
        status, url = self.get_live_stream_url()
        info.status = status
        info.link = url
        
        return info


class LiveDouyin:
    """抖音直播获取"""
    
    BASE_URL = "https://live.douyin.com"
    
    def __init__(self, room_id: str):
        self.room_id = room_id
    
    def get_real_room_id(self) -> str:
        """通过分享链接获取真实房间号"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        
        try:
            # 访问直播间页面，从页面中提取真实房间ID
            page_url = f"{self.BASE_URL}/{self.room_id}"
            resp = requests.get(page_url, headers=headers, timeout=10, allow_redirects=True)
            
            # 从URL中获取真实房间号（如果是短ID会重定向）
            final_url = resp.url
            match = re.search(r'live\.douyin\.com/(\d+)', final_url)
            if match:
                real_room_id = match.group(1)
                douyin_log(f"真实房间号: {real_room_id}", LogLevel.DEBUG)
                return real_room_id
            
            # 从页面源码中提取
            text = resp.text
            patterns = [
                r'"room_id"\s*:\s*"(\d+)"',
                r'"roomId"\s*:\s*"(\d+)"',
                r'"id"\s*:\s*"(\d{10,})"',
                r'room_id=(\d{10,})',
            ]
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    return match.group(1)
            
            # 如果输入的已经是长ID，直接返回
            if len(self.room_id) >= 10:
                return self.room_id
                
            return ""
        except Exception as e:
            error(f"获取抖音真实房间号失败: {e}\n{traceback.format_exc()}")
            return ""
    
    def get_live_stream_url(self) -> Tuple[LiveStreamStatus, str]:
        """
        获取抖音直播流地址
        
        Returns:
            (状态, 流URL)
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": f"{self.BASE_URL}/"
        }
        
        try:
            # 获取真实房间号
            real_room_id = self.get_real_room_id()
            if not real_room_id:
                douyin_log("无法获取真实房间号", LogLevel.WARN)
                return LiveStreamStatus.Absent, ""

            # 使用官方API获取直播流
            url = f"{self.BASE_URL}/webcast/room/web/enter/"
            params = {
                "aid": "6383",
                "room_id": real_room_id
            }
            
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            
            try:
                result = resp.json()
                douyin_log(f"API status_code: {result.get('status_code')}", LogLevel.DEBUG)
                
                if result.get("status_code") == 0:
                    data = result.get("data", {})
                    room_data = data.get("room", {})
                    
                    # 检查是否开播 (status=2 表示正在直播)
                    room_status = room_data.get("status")
                    douyin_log(f"直播间状态: {room_status} (2=直播中)", LogLevel.DEBUG)
                    
                    if room_status != 2:
                        return LiveStreamStatus.NotLive, ""
                    
                    # 获取流地址
                    stream_data = data.get("stream_url", {})
                    hls_pull_url_map = stream_data.get("hls_pull_url_map", {})
                    
                    if hls_pull_url_map:
                        # 优先原画
                        url = hls_pull_url_map.get("FULL_HD") or hls_pull_url_map.get("HD") or hls_pull_url_map.get("SD")
                        if url:
                            return LiveStreamStatus.Normal, url
                    
                    # 尝试其他格式
                    hls_pull_url = stream_data.get("hls_pull_url", "")
                    if hls_pull_url:
                        return LiveStreamStatus.Normal, hls_pull_url
                        
            except json.JSONDecodeError:
                pass
            
            # 方法2: 直接请求页面提取
            page_url = f"{self.BASE_URL}/{real_room_id}"
            page_resp = requests.get(page_url, headers=headers, timeout=10)
            page_text = page_resp.text
            
            stream_url = self._extract_stream_url(page_text)
            if stream_url:
                return LiveStreamStatus.Normal, stream_url
            
            # 检查直播间状态
            if '"is_live":false' in page_text or '"isLive":false' in page_text:
                return LiveStreamStatus.NotLive, ""
            
            if "404" in page_text or "不存在" in page_text or page_resp.status_code == 404:
                return LiveStreamStatus.Absent, ""
            
            return LiveStreamStatus.Error, ""
            
        except Exception as e:
            error(f"获取抖音直播流失败: {e}\n{traceback.format_exc()}")
            return LiveStreamStatus.Error, ""
    
    def _extract_stream_url(self, text: str) -> str:
        """从页面提取流URL"""
        patterns = [
            r'"hls_pull_url_map"\s*:\s*\{\s*"FULL_HD"\s*:\s*"([^"]+)"',
            r'"hls_pull_url_map"\s*:\s*\{\s*"HD"\s*:\s*"([^"]+)"',
            r'"hls_pull_url"\s*:\s*"([^"]+)"',
            r'"flv_pull_url"\s*:\s*\{\s*"FULL_HD"\s*:\s*"([^"]+)"',
            r'"stream_url"\s*:\s*\{\s*"live_core_url"\s*:\s*"([^"]+)"',
            r'"pull_url_map"\s*:\s*\{\s*"HLS"\s*:\s*\{\s*"url"\s*:\s*"([^"]+)"',
            r'"hlsUrl"\s*:\s*"([^"]+)"',
            r'rtmp://[^"\\]+',
            r'https?://[^"\\]+\.m3u8[^"\\]*',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                url = match.group(1)
                url = url.replace("\\/", "/")
                if url.startswith("http") and "m3u8" in url:
                    return url
        
        return ""
    
    def get_room_info(self) -> Dict[str, Any]:
        """获取直播间信息"""
        real_room_id = self.get_real_room_id()
        if not real_room_id:
            return {}
        
        url = f"{self.BASE_URL}/webcast/room/web/enter/"
        params = {
            "aid": "6383",
            "room_id": real_room_id
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            
            if result.get("status_code") == 0:
                data = result.get("data", {})
                return {
                    "title": data.get("room", {}).get("title", ""),
                    "nickname": data.get("user", {}).get("nickname", ""),
                    "status": data.get("room", {}).get("status", 0)
                }
            return {}
        except Exception:
            return {}
    
    def get_live_stream_info(self) -> LiveStreamInfo:
        """获取完整的直播流信息"""
        info = LiveStreamInfo()
        info.room_id = self.room_id
        
        status, url = self.get_live_stream_url()
        info.status = status
        info.link = url
        
        room_info = self.get_room_info()
        info.title = room_info.get("title", "")
        info.uname = room_info.get("nickname", "")
        
        return info


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
