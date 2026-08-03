# -*- coding: utf-8 -*-
"""匿名访客 cookie（novel_web_id）本地缓存

- 首次生成后写入 cookie.json（项目根目录）
- 后续直接复用缓存；请求被风控（403/429）时才重新生成
"""
import json
import random
from pathlib import Path

COOKIE_PATH = Path(__file__).resolve().parent.parent / "cookie.json"


def load_cookie() -> str | None:
    try:
        data = json.loads(COOKIE_PATH.read_text(encoding="utf-8"))
        v = data.get("novel_web_id")
        return str(v) if v else None
    except (OSError, ValueError):
        return None


def save_cookie(value: str) -> None:
    try:
        COOKIE_PATH.write_text(
            json.dumps({"novel_web_id": value}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError:
        pass


def get_or_create_cookie() -> str:
    """优先读缓存；不存在则生成并保存"""
    cached = load_cookie()
    if cached:
        return cached
    value = str(random.randint(10**18, 10**19 - 1))
    save_cookie(value)
    return value


__all__ = ["load_cookie", "save_cookie", "get_or_create_cookie"]
