# -*- coding: utf-8 -*-
"""核心下载逻辑：目录 API + SSR 正文抓取 + 字体混淆解密"""
import re
import time

from curl_cffi import requests as req
from lxml import etree

from .font_map import FONT_MAP

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TIMEOUT = 25
MIN_CONTENT = 100  # 正文低于该长度视为预览/付费章节
RETRIES = 3

DIR_API = "https://fanqienovel.com/api/reader/directory/detail?bookId={book_id}&aid=1967"
PAGE_URL = "https://fanqienovel.com/page/{book_id}"
READER_URL = "https://fanqienovel.com/reader/{item_id}"


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


def _headers(cookie: str = "") -> dict:
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if cookie:
        h["Cookie"] = cookie
    return h


class Novel:
    """一本书的目录信息"""

    def __init__(self, book_id: str, title: str, chapters: list):
        self.book_id = book_id
        self.title = title
        self.chapters = chapters  # [{itemId, title, needPay, ...}]


def get_book(book_id: str) -> Novel:
    """通过目录 API 获取书名与章节列表（无需登录/签名）"""
    r = req.get(DIR_API.format(book_id=book_id), headers=_headers(),
                impersonate="chrome", timeout=TIMEOUT)
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"目录接口返回错误: {data.get('message')}")
    d = data["data"]
    chapters = [c for vol in d.get("chapterListWithVolume", []) for c in vol]
    title = d.get("bookName") or _fetch_page_title(book_id)
    return Novel(book_id, title, chapters)


def _fetch_page_title(book_id: str) -> str:
    """兜底：从目录页解析书名"""
    try:
        r = req.get(PAGE_URL.format(book_id=book_id), headers=_headers(),
                    impersonate="chrome", timeout=TIMEOUT)
        ele = etree.HTML(r.text)
        titles = ele.xpath("//h1/text()")
        return titles[0].strip() if titles else f"book_{book_id}"
    except Exception:
        return f"book_{book_id}"


def fetch_chapter(item_id: str, cookie: str = "") -> str:
    """抓取章节页 SSR，返回混淆正文（未解密）"""
    headers = _headers(cookie)
    r = req.get(READER_URL.format(item_id=item_id), headers=headers,
                impersonate="chrome", timeout=TIMEOUT)
    r.raise_for_status()
    ele = etree.HTML(r.text)
    paras = ele.xpath(
        '//div[contains(@class, "muye-reader-content")]//p/text()')
    return "\n".join(p.strip() for p in paras if p.strip())


def decrypt(text: str) -> str:
    """按字体映射表还原混淆字符"""
    return "".join(FONT_MAP.get(ord(ch), ch) for ch in text)


def download_chapter(item_id: str, cookie: str = "") -> str:
    """抓取并解密单个章节，失败返回空串"""
    last_err = None
    for attempt in range(RETRIES):
        try:
            raw = fetch_chapter(item_id, cookie)
            if len(raw) < MIN_CONTENT:
                return ""
            return decrypt(raw)
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1 * (attempt + 1))
    raise RuntimeError(f"章节 {item_id} 下载失败: {last_err}")
