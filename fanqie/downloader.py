# -*- coding: utf-8 -*-
"""核心下载逻辑：目录 API + SSR 正文抓取 + 字体混淆解密

反封控设计（分层）:
  1. TLS 指纹  -> curl_cffi impersonate="chrome"（绕过 TLS 指纹检测）
  2. 请求头    -> 完整真实浏览器头（UA 轮换 / Sec-Fetch-* / Accept 等）
  3. 频率      -> 随机延迟节奏 + 失败指数退避（尊重 Retry-After）
  4. 会话      -> 复用 Session + 匿名 novel_web_id cookie，行为接近真实用户
"""
import random
import re

from curl_cffi import requests as req
from lxml import etree

from .font_map import FONT_MAP
from .headers import api_headers, page_headers, random_ua
from .pacing import Pacing, backoff_sleep, parse_retry_after

TIMEOUT = 25
MIN_CONTENT = 100   # 正文低于该长度视为预览/付费章节
RETRIES = 3
HOST = "fanqienovel.com"
DIR_API = f"https://{HOST}/api/reader/directory/detail?bookId={{book_id}}&aid=1967"
PAGE_URL = f"https://{HOST}/page/{{book_id}}"
READER_URL = f"https://{HOST}/reader/{{item_id}}"
HOME_URL = f"https://{HOST}/"


def parse_book_id(text: str) -> str:
    """从输入解析书 ID：纯数字，或包含 book_id= 的链接"""
    text = text.strip()
    if text.isdigit():
        return text
    m = re.search(r"book_id=(\d+)", text)
    if m:
        return m.group(1)
    m = re.search(r"/(?:page|reader|book)/(\d+)", text)
    if m:
        return m.group(1)
    raise ValueError(f"无法从输入解析书 ID: {text!r}")


class Client:
    """伪装浏览器身份的请求客户端"""

    def __init__(self, delay_min: float = 1.0, delay_max: float = 3.0):
        self.session = req.Session(impersonate="chrome")
        self.pacing = Pacing(delay_min, delay_max)
        # 匿名访客 cookie：模拟一个稳定的阅读会话
        self.ua = random_ua()
        self.session.cookies.set(
            "novel_web_id",
            str(random.randint(10**18, 10**19 - 1)),
            domain=HOST,
        )

    def _rotate_ua(self) -> str:
        self.ua = random_ua()
        return self.ua

    def get(self, url: str, kind: str = "page", referer: str | None = None,
            retries: int = RETRIES):
        """带节奏控制、退避重试的 GET 请求"""
        last_resp = None
        for attempt in range(retries):
            self.pacing.wait()  # 请求前随机延迟（限速）
            headers = (page_headers(self.ua, referer) if kind == "page"
                       else api_headers(self.ua, referer))
            try:
                resp = self.session.get(url, headers=headers, timeout=TIMEOUT)
            except Exception as e:  # noqa: BLE001
                last_resp = e
                if attempt < retries - 1:
                    backoff_sleep(attempt)
                    self._rotate_ua()
                continue

            # 触发限流 / 风控 / 服务器错误 → 退避重试
            if resp.status_code in (429, 403) or resp.status_code >= 500:
                last_resp = resp
                if attempt < retries - 1:
                    retry_after = parse_retry_after(
                        resp.headers.get("Retry-After"))
                    backoff_sleep(attempt, retry_after=retry_after)
                    self._rotate_ua()
                continue
            return resp
        raise RuntimeError(f"请求失败(重试{retries}次): {last_resp}")


class Novel:
    """一本书的目录信息"""

    def __init__(self, book_id: str, title: str, chapters: list):
        self.book_id = book_id
        self.title = title
        self.chapters = chapters  # [{itemId, title, needPay, ...}]


def get_book(client: Client, book_id: str) -> Novel:
    """通过目录 API 获取书名与章节列表（无需登录/签名）"""
    resp = client.get(DIR_API.format(book_id=book_id), kind="api",
                      referer=HOME_URL)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"目录接口返回错误: {data.get('message')}")
    d = data["data"]
    chapters = [c for vol in d.get("chapterListWithVolume", []) for c in vol]
    title = d.get("bookName") or _fetch_page_title(client, book_id)
    return Novel(book_id, title, chapters)


def _fetch_page_title(client: Client, book_id: str) -> str:
    """兜底：从目录页解析书名"""
    try:
        resp = client.get(PAGE_URL.format(book_id=book_id), kind="page",
                          referer=HOME_URL)
        ele = etree.HTML(resp.text)
        titles = ele.xpath("//h1/text()")
        return titles[0].strip() if titles else f"book_{book_id}"
    except Exception:  # noqa: BLE001
        return f"book_{book_id}"


def fetch_chapter(client: Client, item_id: str,
                  referer: str | None = None) -> str:
    """抓取章节页 SSR，返回混淆正文（未解密）"""
    return fetch_chapter_page(client, item_id, referer)[0]


def fetch_chapter_page(client: Client, item_id: str,
                       referer: str | None = None) -> tuple:
    """抓取章节页，返回 (混淆正文, 章节字数 chapterWordNumber)"""
    resp = client.get(READER_URL.format(item_id=item_id), kind="page",
                      referer=referer or PAGE_URL)
    resp.raise_for_status()
    html = resp.text
    ele = etree.HTML(html)
    paras = ele.xpath(
        '//div[contains(@class, "muye-reader-content")]//p/text()')
    raw = "\n".join(p.strip() for p in paras if p.strip())
    m = re.search(r"chapterWordNumber[\"']?\s*[:=]\s*[\"']?(\d+)", html)
    word_count = int(m.group(1)) if m else None
    return raw, word_count


def decrypt(text: str) -> str:
    """按字体映射表还原混淆字符"""
    return "".join(FONT_MAP.get(ord(ch), ch) for ch in text)


def download_chapter(client: Client, item_id: str,
                     referer: str | None = None) -> str:
    """抓取并解密单个章节，内容不足返回空串"""
    raw, _ = fetch_chapter_page(client, item_id, referer)
    if len(raw) < MIN_CONTENT:
        return ""
    return decrypt(raw)


def download_chapter_with_info(client: Client, item_id: str,
                               referer: str | None = None) -> tuple:
    """抓取并解密章节，返回 (正文, 章节字数)"""
    raw, word_count = fetch_chapter_page(client, item_id, referer)
    if len(raw) < MIN_CONTENT:
        return "", word_count
    return decrypt(raw), word_count


__all__ = [
    "Client", "Novel", "get_book", "fetch_chapter", "fetch_chapter_page",
    "decrypt", "download_chapter", "download_chapter_with_info",
    "parse_book_id",
]
