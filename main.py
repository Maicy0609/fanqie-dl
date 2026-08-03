#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fanqie-dl 命令行入口

用法:
    python main.py <书ID或链接>                下载全书
    python main.py <书ID> --start 1 --end 10   下载 1~10 章
    python main.py <书ID> --list               仅列出章节
    python main.py <书ID> --out ./books        指定输出目录
"""
import argparse
import sys
import time
from pathlib import Path

from tqdm import tqdm

from fanqie import __version__
from fanqie.downloader import (
    download_chapter, get_book, parse_book_id, decrypt,
)

BOOK_ID_HELP = "小说 ID，或包含 book_id= 的分享链接"


def sanitize(name: str) -> str:
    for bad, good in [("<", "＜"), (">", "＞"), (":", "："), ('"', "＂"),
                      ("/", "／"), ("\\", "＼"), ("|", "｜"), ("?", "？"),
                      ("*", "＊")]:
        name = name.replace(bad, good)
    return name


def cmd_list(novel) -> None:
    print(f"《{novel.title}》 共 {len(novel.chapters)} 章")
    for i, ch in enumerate(novel.chapters, 1):
        lock = "🔒" if ch.get("needPay") else "  "
        print(f"  {i:>4}. {lock} {ch['title']}")


def cmd_download(novel, start: int, end: int, out_dir: Path) -> None:
    total = len(novel.chapters)
    start = max(1, start)
    end = min(total, end) if end else total
    sel = novel.chapters[start - 1:end]
    print(f"《{novel.title}》 共 {total} 章，下载 [{start}~{end}] 共 {len(sel)} 章")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{sanitize(novel.title)}.txt"

    ok, skipped, failed = 0, 0, 0
    t0 = time.time()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"《{novel.title}》\n")
        for idx, ch in tqdm(enumerate(sel, start), total=len(sel),
                            unit="章", ncols=80):
            try:
                content = download_chapter(ch["itemId"])
                if not content:
                    skipped += 1
                    print(f"\n⚠️ 第{idx}章《{ch['title']}》疑似预览/付费，跳过")
                    continue
                f.write(f"\n\n{ch['title']}\n\n{content}\n")
                f.flush()
                ok += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"\n❌ 第{idx}章《{ch['title']}》失败: {e}")

    cost = time.time() - t0
    print(f"\n🎉 完成: 成功 {ok} 章, 跳过 {skipped}, 失败 {failed}, 耗时 {cost:.0f}s")
    print(f"📁 输出: {out_path}")
    if failed:
        print("提示: 失败章节可缩小范围重试: --start N --end N")


def main() -> None:
    ap = argparse.ArgumentParser(description="番茄小说下载器 (fanqie-dl)")
    ap.add_argument("book", help=BOOK_ID_HELP)
    ap.add_argument("--start", type=int, default=1, help="起始章节（默认1）")
    ap.add_argument("--end", type=int, default=0, help="结束章节（默认全书）")
    ap.add_argument("--list", action="store_true", help="仅列出章节")
    ap.add_argument("--out", default="books", help="输出目录（默认 ./books）")
    ap.add_argument("--version", action="version", version=f"fanqie-dl {__version__}")
    args = ap.parse_args()

    try:
        book_id = parse_book_id(args.book)
    except ValueError as e:
        print(e)
        sys.exit(1)

    print(f"正在获取《{book_id}》目录...")
    novel = get_book(book_id)
    if not novel.chapters:
        print("❌ 未获取到章节（可能书不存在或需登录）")
        sys.exit(1)

    if args.list:
        cmd_list(novel)
        return
    cmd_download(novel, args.start, args.end, Path(args.out))


if __name__ == "__main__":
    main()
