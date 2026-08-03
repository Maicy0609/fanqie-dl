#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fanqie-dl 命令行入口

用法:
    python main.py <书ID或链接>                         下载全书
    python main.py <书ID> --start 1 --end 10            下载 1~10 章
    python main.py --search 关键词                      搜索选书（一条龙）
    python main.py --search 关键词 --pick 2             直接下载第2个结果
    python main.py <书ID> --meta                        查看书籍/章节元数据
    python main.py <书ID> --list                        仅列出章节
    python main.py <书ID> --cover                       下载时同时保存封面
    python main.py <书ID> --out ./books                 指定输出目录
    python main.py <书ID> --delay-min 2 --delay-max 5   调节请求间隔(秒)
"""
import argparse
import sys
import time
from pathlib import Path

from tqdm import tqdm

from fanqie import __version__
from fanqie.downloader import (
    Client, download_chapter_with_info, get_book, parse_book_id,
)
from fanqie.headers import page_headers
from fanqie.meta import build_meta, fmt_time, render_summary
from fanqie.search import search_books

BOOK_ID_HELP = "小说 ID，或包含 book_id= 的分享链接"


def sanitize(name: str) -> str:
    for bad, good in [("<", "＜"), (">", "＞"), (":", "："), ('"', "＂"),
                      ("/", "／"), ("\\", "＼"), ("|", "｜"), ("?", "？"),
                      ("*", "＊")]:
        name = name.replace(bad, good)
    return name


def _status_text(s: str) -> str:
    return "已完结" if s == "0" else ("连载中" if s == "1" else s)


def cmd_list(novel) -> None:
    print(f"《{novel.title}》 共 {len(novel.chapters)} 章")
    for i, ch in enumerate(novel.chapters, 1):
        lock = "🔒" if ch.get("needPay") else "  "
        print(f"  {i:>4}. {lock} {ch['title']}")


def cmd_meta(client: Client, book_id: str) -> None:
    """查看书籍与章节元数据"""
    meta = build_meta(client, book_id)
    print(render_summary(meta))
    if meta.chapters:
        print("\n=== 章节列表（含上传时间）===")
        for ch in meta.chapters:
            lock = "🔒" if ch.need_pay else "  "
            print(f"  {ch.order:>4}. {lock} {ch.title} | "
                  f"更新:{fmt_time(ch.publish_time, '%Y-%m-%d')} "
                  f"| {ch.volume}")
    print(f"\n书ID: {meta.book_id}")


def save_cover(client: Client, url: str, path: Path) -> bool:
    """下载封面图"""
    try:
        headers = page_headers(client.ua, referer="https://fanqienovel.com/")
        resp = client.session.get(url, headers=headers, timeout=25)
        if resp.status_code == 200 and resp.content:
            path.write_bytes(resp.content)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def cmd_download(client: Client, book_id: str, start: int, end: int,
                 out_dir: Path, with_cover: bool,
                 title_hint: str | None = None) -> None:
    novel = get_book(client, book_id)  # 自带目录API→页面 双兜底
    if novel.title.startswith("book_") and title_hint:
        novel.title = title_hint  # 搜索结果带回来的书名兜底
    total = len(novel.chapters)
    start = max(1, start)
    end = min(total, end) if end else total
    sel = novel.chapters[start - 1:end]
    print(f"《{novel.title}》 共 {total} 章，下载 [{start}~{end}] 共 {len(sel)} 章")
    print(f"请求间隔: {client.pacing.delay_min:.1f}~{client.pacing.delay_max:.1f}s "
          f"(反封控节奏)")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{sanitize(novel.title)}.txt"

    try:
        meta = build_meta(client, book_id)  # 书籍信息自带兜底
        header = render_summary(meta)
    except Exception:  # noqa: BLE001
        meta = None
        header = f"《{novel.title}》"
    chapter_by_id = {c.item_id: c for c in meta.chapters} if meta else {}

    ok, skipped, failed = 0, 0, 0
    t0 = time.time()
    referer = None
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + "\n\n")
        f.write("=" * 40 + "\n")
        for idx, ch in tqdm(enumerate(sel, start), total=len(sel),
                            unit="章", ncols=80):
            try:
                content, word_count = download_chapter_with_info(
                    client, ch["itemId"], referer)
                referer = (f"https://fanqienovel.com/reader/"
                           f"{ch['itemId']}")
                if not content:
                    skipped += 1
                    print(f"\n⚠️ 第{idx}章《{ch['title']}》疑似预览/付费，跳过")
                    continue
                cm = chapter_by_id.get(ch["itemId"])
                pub = fmt_time(cm.publish_time, "%Y-%m-%d") if cm else "未知"
                words = f"{word_count:,}字" if word_count else "未知"
                f.write(f"\n\n{ch['title']}\n"
                        f"〔字数:{words} | 更新:{pub}〕\n\n{content}\n")
                f.flush()
                ok += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"\n❌ 第{idx}章《{ch['title']}》失败: {e}")

    cover_path = None
    if with_cover and meta and meta.cover_url:
        cover_path = out_dir / f"{sanitize(novel.title)}_cover.jpg"
        if save_cover(client, meta.cover_url, cover_path):
            print(f"\n🖼️ 封面已保存: {cover_path}")
        else:
            cover_path = None
            print("\n⚠️ 封面下载失败（URL 可能已过期）")

    cost = time.time() - t0
    print(f"\n🎉 完成: 成功 {ok} 章, 跳过 {skipped}, 失败 {failed}, 耗时 {cost:.0f}s")
    print(f"📁 正文: {out_path}")
    if cover_path:
        print(f"🖼️ 封面: {cover_path}")
    if failed:
        print("提示: 失败章节可缩小范围重试: --start N --end N")


def cmd_search(client: Client, keyword: str, pick: int | None,
               args) -> None:
    """搜索选书下载一条龙"""
    print(f"🔍 搜索《{keyword}》...")
    try:
        results = search_books(client, keyword)  # 双端点自动回退
    except Exception as e:  # noqa: BLE001
        print(f"❌ 搜索失败: {e}")
        sys.exit(1)
    if not results:
        print("❌ 没有搜索到相关结果")
        sys.exit(1)

    print(f"\n共 {len(results)} 个结果：")
    for i, r in enumerate(results, 1):
        status = _status_text(str(r.get("creation_status", "")))
        score = r.get("score") or "-"
        words = f"{int(r['word_number']):,}字" if r.get("word_number") else ""
        print(f"  {i:>2}. 《{r.get('title')}》 {r.get('author') or ''} "
              f"[{r.get('category') or ''}] {status} 评分{score} {words}")
        print(f"      ID: {r.get('book_id')}")
        ab = (r.get("abstract") or "").strip().replace("\n", " ")
        if ab:
            print(f"      简介: {ab[:80]}...")

    # 选书
    if pick:
        idx = pick
    else:
        try:
            inp = input("\n输入序号下载该书（回车退出）: ").strip()
            idx = int(inp) if inp else 0
        except (EOFError, KeyboardInterrupt):
            idx = 0
    if not (1 <= idx <= len(results)):
        print("已取消。")
        return
    picked = results[idx - 1]
    print(f"\n📥 选择下载《{picked.get('title')}》 (ID={picked.get('book_id')})")
    cmd_download(client, picked["book_id"], args.start, args.end,
                 Path(args.out), args.cover, picked.get("title"))


def main() -> None:
    ap = argparse.ArgumentParser(description="番茄小说下载器 (fanqie-dl)")
    ap.add_argument("book", nargs="?", help=BOOK_ID_HELP)
    ap.add_argument("--search", metavar="关键词", help="搜索选书（一条龙）")
    ap.add_argument("--pick", type=int, default=0,
                    help="与--search联用：直接下载第N个结果")
    ap.add_argument("--start", type=int, default=1, help="起始章节（默认1）")
    ap.add_argument("--end", type=int, default=0, help="结束章节（默认全书）")
    ap.add_argument("--meta", action="store_true",
                    help="查看书籍/章节元数据（不下载正文）")
    ap.add_argument("--list", action="store_true", help="仅列出章节")
    ap.add_argument("--cover", action="store_true", help="下载封面图")
    ap.add_argument("--out", default="books", help="输出目录（默认 ./books）")
    ap.add_argument("--delay-min", type=float, default=1.0,
                    help="请求间隔下限(秒)，默认1.0")
    ap.add_argument("--delay-max", type=float, default=3.0,
                    help="请求间隔上限(秒)，默认3.0（上限需≥下限）")
    ap.add_argument("--version", action="version",
                    version=f"fanqie-dl {__version__}")
    args = ap.parse_args()

    if args.delay_max < args.delay_min:
        print("❌ --delay-max 不能小于 --delay-min")
        sys.exit(1)

    client = Client(args.delay_min, args.delay_max)

    # 搜索模式：无需书ID
    if args.search:
        cmd_search(client, args.search, args.pick, args)
        return

    if not args.book:
        ap.print_help()
        sys.exit(1)

    try:
        book_id = parse_book_id(args.book)
    except ValueError as e:
        print(e)
        sys.exit(1)

    if args.meta:
        print(f"正在获取《{book_id}》元数据...")
        cmd_meta(client, book_id)
        return

    print(f"正在获取《{book_id}》目录...")
    novel = get_book(client, book_id)
    if not novel.chapters:
        print("❌ 未获取到章节（可能书不存在或需登录）")
        sys.exit(1)

    if args.list:
        cmd_list(novel)
        return
    cmd_download(client, book_id, args.start, args.end, Path(args.out),
                 args.cover)


if __name__ == "__main__":
    main()
