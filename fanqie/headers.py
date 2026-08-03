# -*- coding: utf-8 -*-
"""浏览器身份伪装：User-Agent 轮换池 + 完整真实请求头

参考:
- NanmiCoder/CrawlerTutorial《反爬虫对抗基础：请求伪装》
- Chrome DevTools 实际请求头
"""
import random

# 桌面端 UA 池（Chrome / Edge / Firefox / Safari，Windows + macOS）
USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Chrome macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    # Firefox Windows / macOS
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Safari macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# Sec-CH-UA 需要与具体 UA 匹配才真实；这里按 Chrome 系/其他做两组
_CHROME_SEC_CH_UA = ('"Not_A Brand";v="8", "Chromium";v="120", '
                     '"Google Chrome";v="120"')
_CHROME_PLATFORM = '"Windows"'
_OTHER_SEC_CH_UA = '"Not_A Brand";v="99", "Gecko";v="122", "Firefox";v="122"'


def random_ua() -> str:
    """随机选一个桌面 UA"""
    return random.choice(USER_AGENTS)


def page_headers(ua: str | None = None, referer: str | None = None) -> dict:
    """HTML 页面请求头（document 导航）"""
    ua = ua or random_ua()
    is_chrome = "Chrome" in ua or "Edg" in ua
    h = {
        "User-Agent": ua,
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,image/apng,*/*;q=0.8,"
                   "application/signed-exchange;v=b3;q=0.7"),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Sec-Ch-Ua": _CHROME_SEC_CH_UA if is_chrome else _OTHER_SEC_CH_UA,
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": _CHROME_PLATFORM if is_chrome else '"macOS"',
    }
    if referer:
        h["Referer"] = referer
    return h


def api_headers(ua: str | None = None, referer: str | None = None) -> dict:
    """XHR/API 请求头（fetch 请求）"""
    ua = ua or random_ua()
    is_chrome = "Chrome" in ua or "Edg" in ua
    h = {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Ch-Ua": _CHROME_SEC_CH_UA if is_chrome else _OTHER_SEC_CH_UA,
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": _CHROME_PLATFORM if is_chrome else '"macOS"',
    }
    if referer:
        h["Referer"] = referer
    return h
