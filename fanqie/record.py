# -*- coding: utf-8 -*-
"""下载记录（JSON）：每本书一个，记录 book_id / 标题 / 状态 / 已下载章节序号

用于「连载下载更新」：扫描连载中书籍、校验下载连续性、追加新章节。
"""
import json
from datetime import datetime
from pathlib import Path


def record_path(book_dir: Path, safe_title: str) -> Path:
    return book_dir / f"{safe_title}.json"


def load_record(book_dir: Path, safe_title: str) -> dict:
    p = record_path(book_dir, safe_title)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def save_record(book_dir: Path, safe_title: str, record: dict) -> Path:
    p = record_path(book_dir, safe_title)
    p.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return p


def scan_records(base_dir: Path) -> list:
    """扫描下载目录下所有书籍记录，附 _dir/_file 字段"""
    records = []
    if not base_dir.is_dir():
        return records
    for p in base_dir.rglob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            if rec.get("book_id"):
                rec["_dir"] = p.parent
                rec["_file"] = p
                records.append(rec)
        except (OSError, ValueError):
            continue
    return records


def new_record(book_id: str, title: str, status: str = "未知") -> dict:
    return {
        "book_id": book_id,
        "title": title,
        "status": status,
        "downloaded_orders": [],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def merge_orders(record: dict, new_orders: list) -> list:
    orders = set(record.get("downloaded_orders", []) or [])
    orders.update(int(o) for o in new_orders if str(o).isdigit())
    return sorted(orders)


__all__ = ["record_path", "load_record", "save_record", "scan_records",
           "new_record", "merge_orders"]
