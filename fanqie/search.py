# -*- coding: utf-8 -*-
"""关键词搜索（无需签名）

端点来源: Tomato Novel Downloader 项目实战帖（AtomGit/GitCode）
  https://novel.snssdk.com/api/novel/channel/homepage/search/search/v1/
  备用: https://api-lf.fanqiesdk.com/api/novel/channel/homepage/search/search/v1/
两者均实测返回 code=0，无需 a_bogus/msToken 签名。
"""
from urllib.parse import quote, urlencode

from .downloader import Client

SEARCH_API = ("https://novel.snssdk.com/api/novel/channel/homepage/"
              "search/search/v1/")
SEARCH_API_BACKUP = ("https://api-lf.fanqiesdk.com/api/novel/channel/"
                     "homepage/search/search/v1/")
SEARCH_REFERER = "https://fanqienovel.com/search/"


def search_books(client: Client, keyword: str, offset: int = 0,
                 limit: int = 20, retries_backup: bool = True) -> list:
    """搜索书籍，返回结果列表（dict）

    每个结果含: book_id, title, author, abstract, category,
                creation_status, score, thumb_url
    """
    params = {
        "device_platform": "android",
        "parent_enterfrom": "novel_channel_search.tab.",
        "offset": str(offset),
        "limit": str(limit),
        "aid": "1967",
        "q": keyword,
    }
    qs = urlencode(params)
    referer = SEARCH_REFERER + quote(keyword)
    urls = [f"{SEARCH_API}?{qs}"]
    if retries_backup:
        urls.append(f"{SEARCH_API_BACKUP}?{qs}")

    last_err = None
    for url in urls:
        try:
            resp = client.get(url, kind="api", referer=referer)
            data = resp.json()
            if data is None or data.get("code") != 0:
                raise RuntimeError(f"搜索接口异常: "
                                   f"{data.get('message') if data else '空响应'}")
            return data.get("data", {}).get("ret_data", []) or []
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"搜索失败(主/备接口均不可用): {last_err}")


__all__ = ["search_books"]
