# -*- coding: utf-8 -*-
"""书籍/章节元数据采集（APP 版可见信息）

来源:
  - 书籍信息: GET /api/book/info?bookId={id}
      书名/作者/封面/简介/标签/总字数/阅读量/状态/最新章节/最近更新
  - 章节列表: GET /api/reader/directory/detail?bookId={id}&aid=1967
      章节ID/标题/顺序/卷名/付费标记/上传时间(firstPassTime)
  - 章节字数: 章节页 SSR 中的 chapterWordNumber（下载正文时顺带解析）
"""
import json
from dataclasses import dataclass, field
from datetime import datetime

from lxml import etree

from .downloader import DIR_API, HOME_URL, HOST, Client

BOOK_INFO_API = f"https://{HOST}/api/book/info?bookId={{book_id}}"
PAGE_URL = f"https://{HOST}/page/{{book_id}}"


def _ts(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fmt_time(ts: int | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not ts:
        return "未知"
    try:
        return datetime.fromtimestamp(ts).strftime(fmt)
    except (OverflowError, OSError, ValueError):
        return "未知"


@dataclass
class ChapterMeta:
    item_id: str
    order: int
    title: str
    volume: str = ""
    need_pay: bool = False
    word_count: int | None = None   # 下载正文时补全
    publish_time: int | None = None


@dataclass
class BookMeta:
    book_id: str
    title: str
    author: str = ""
    cover_url: str | None = None
    abstract: str | None = None
    description: str | None = None
    tags: list = field(default_factory=list)
    total_words: int | None = None
    read_count: int | None = None
    status: str = ""
    last_update: int | None = None
    last_chapter: str = ""
    chapter_count: int = 0
    chapters: list = field(default_factory=list)


def fetch_book_info(client: Client, book_id: str) -> dict:
    """通过 /api/book/info 获取书籍元数据"""
    resp = client.get(BOOK_INFO_API.format(book_id=book_id), kind="api",
                      referer=HOME_URL)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"书籍信息接口错误: {data.get('message')}")
    return data.get("data") or {}


def parse_tags(info: dict) -> list:
    """解析 categoryV2（JSON 字符串）中的标签名"""
    raw = info.get("categoryV2") or "[]"
    try:
        cats = json.loads(raw)
        return [c.get("Name") for c in cats if c.get("Name")]
    except (json.JSONDecodeError, TypeError):
        return []


def _info_to_meta(book_id: str, info: dict, chapters: list) -> BookMeta:
    return BookMeta(
        book_id=book_id,
        title=info.get("bookName") or f"book_{book_id}",
        author=info.get("authorName") or info.get("author") or "",
        cover_url=info.get("thumbUri") or info.get("thumbUrl"),
        abstract=info.get("abstract"),
        description=info.get("description"),
        tags=parse_tags(info),
        total_words=_ts(info.get("wordNumber")),
        read_count=_ts(info.get("readCount")),
        status="连载中" if info.get("status") == "1" else "已完结",
        last_update=_ts(info.get("lastPublishTime")),
        last_chapter=info.get("lastChapterTitle") or "",
        chapter_count=len(chapters),
        chapters=chapters,
    )


def fetch_directory(client: Client, book_id: str) -> list:
    """获取章节列表（含上传时间 firstPassTime）"""
    resp = client.get(DIR_API.format(book_id=book_id), kind="api",
                      referer=HOME_URL)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"目录接口错误: {data.get('message')}")
    d = data["data"]
    chapters = []
    for vol in d.get("chapterListWithVolume", []):
        for c in vol:
            chapters.append(ChapterMeta(
                item_id=c["itemId"],
                order=_ts(c.get("realChapterOrder")) or 0,
                title=c["title"],
                volume=c.get("volume_name", ""),
                need_pay=bool(c.get("needPay")),
                publish_time=_ts(c.get("firstPassTime")),
            ))
    chapters.sort(key=lambda c: c.order)
    return chapters


def parse_page_word_count(html: str) -> int | None:
    """从章节页 SSR 提取 chapterWordNumber"""
    import re
    m = re.search(r"chapterWordNumber[\"']?\s*[:=]\s*[\"']?(\d+)", html)
    return int(m.group(1)) if m else None


def build_meta(client: Client, book_id: str) -> BookMeta:
    """聚合书籍信息 + 章节列表"""
    chapters = fetch_directory(client, book_id)
    try:
        info = fetch_book_info(client, book_id)
        return _info_to_meta(book_id, info, chapters)
    except Exception:  # noqa: BLE001 书籍信息接口失败时降级
        return BookMeta(book_id=book_id, title=f"book_{book_id}",
                        chapter_count=len(chapters), chapters=chapters)


def render_summary(meta: BookMeta) -> str:
    """生成书籍信息文本块"""
    lines = [f"《{meta.title}》"]
    if meta.author:
        lines.append(f"作者：{meta.author}")
    if meta.tags:
        lines.append(f"标签：{' / '.join(meta.tags)}")
    if meta.status:
        lines.append(f"状态：{meta.status}")
    if meta.total_words is not None:
        lines.append(f"总字数：{meta.total_words:,}")
    if meta.read_count is not None:
        lines.append(f"阅读量：{meta.read_count:,}")
    if meta.last_chapter:
        lines.append(f"最新章节：{meta.last_chapter}")
    lines.append(f"最近更新：{fmt_time(meta.last_update)}")
    lines.append(f"章节数：{meta.chapter_count}")
    if meta.cover_url:
        lines.append(f"封面：{meta.cover_url}")
    if meta.abstract:
        lines.append(f"\n简介：\n{meta.abstract}")
    return "\n".join(lines)


__all__ = [
    "BookMeta", "ChapterMeta", "build_meta", "fetch_directory",
    "fetch_book_info", "parse_page_word_count", "render_summary", "fmt_time",
]
