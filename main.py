#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fanqie-dl 命令行入口

交互模式（直接运行本程序）:
    1. 下载     输入书本ID或分享链接（自动清洗提取ID），选择保存位置
    2. 搜索     输入关键词 -> 列出完整书名 -> 选择下载
    3. 批量下载 提供文本文件（一行一个链接/ID）
    4. 设置     下载间隔、默认保存目录（保存到 config.json）
    无退出菜单项，按 Ctrl+C 退出

命令行模式:
    python main.py <书ID或链接> --start 1 --end 10 --cover
    python main.py --search 关键词 [--pick N]
    python main.py <书ID> --meta / --list
    python main.py --delay-min 1 --delay-max 3
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

from tqdm import tqdm

from fanqie import __version__
from fanqie.config import load_config, save_config
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


def ask(prefix: str, default: str = "") -> str:
    """交互输入；提供默认值时直接回车取默认值"""
    if default:
        try:
            s = input(f"{prefix} [默认: {default}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise
        return s if s else default
    try:
        return input(f"{prefix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise


def clear_screen() -> None:
    """清屏（Linux/Windows 通用）"""
    os.system("cls" if os.name == "nt" else "clear")


def divider(char: str = "=", width: int = 56) -> None:
    print(char * width)


def pause_return() -> None:
    """提示按回车返回菜单"""
    try:
        input("-- 按回车返回菜单 --")
    except (EOFError, KeyboardInterrupt):
        raise


def _status_text(s: str) -> str:
    return "已完结" if s == "0" else ("连载中" if s == "1" else s)


def cmd_list(novel) -> None:
    print(f"《{novel.title}》 共 {len(novel.chapters)} 章")
    for i, ch in enumerate(novel.chapters, 1):
        lock = "[付费]" if ch.get("needPay") else "      "
        print(f"  {i:>4}. {lock} {ch['title']}")


def cmd_meta(client: Client, book_id: str) -> None:
    meta = build_meta(client, book_id)
    print(render_summary(meta))
    if meta.chapters:
        print("\n=== 章节列表（含上传时间）===")
        for ch in meta.chapters:
            lock = "[付费]" if ch.need_pay else "      "
            print(f"  {ch.order:>4}. {lock} {ch.title} | "
                  f"更新:{fmt_time(ch.publish_time, '%Y-%m-%d')} "
                  f"| {ch.volume}")
    print(f"\n书ID: {meta.book_id}")


def save_cover(client: Client, url: str, path: Path) -> bool:
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
                 base_dir: Path, with_cover: bool = True,
                 title_hint: str | None = None) -> bool:
    """下载一本书到 base_dir/<书名>/ 目录（含 TXT 与封面）"""
    novel = get_book(client, book_id)
    if novel.title.startswith("book_") and title_hint:
        novel.title = title_hint
    total = len(novel.chapters)
    if total == 0:
        print("[x] 未获取到章节（可能书不存在或需登录）")
        return False
    start = max(1, start)
    end = min(total, end) if end else total
    sel = novel.chapters[start - 1:end]
    safe = sanitize(novel.title)
    book_dir = base_dir / safe
    book_dir.mkdir(parents=True, exist_ok=True)
    out_path = book_dir / f"{safe}.txt"
    divider("-")
    print(f"《{novel.title}》 共 {total} 章，下载 [{start}~{end}] 共 {len(sel)} 章")
    print(f"保存目录: {book_dir}")
    divider("-")

    try:
        meta = build_meta(client, book_id)
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
                            unit="章", ncols=70):
            try:
                content, word_count = download_chapter_with_info(
                    client, ch["itemId"], referer)
                referer = (f"https://fanqienovel.com/reader/"
                           f"{ch['itemId']}")
                if not content:
                    skipped += 1
                    print(f"\n[!] 第{idx}章《{ch['title']}》疑似预览/付费，跳过")
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
                print(f"\n[x] 第{idx}章《{ch['title']}》失败: {e}")

    cover_path = None
    if with_cover and meta and meta.cover_url:
        cover_path = book_dir / f"{safe}_cover.jpg"
        if save_cover(client, meta.cover_url, cover_path):
            print(f"\n[ok] 封面已保存: {cover_path}")
        else:
            cover_path = None
            print("\n[!] 封面下载失败（URL 可能已过期）")

    cost = time.time() - t0
    print(f"\n[完成] 成功 {ok} 章, 跳过 {skipped}, 失败 {failed}, 耗时 {cost:.0f}s")
    print(f"[文件] {out_path}")
    if cover_path:
        print(f"[封面] {cover_path}")
    return failed == 0


def flow_download(client: Client, cfg: dict, spec: str,
                  title_hint: str | None = None,
                  ask_dir: bool = True, ask_range: bool = True,
                  start: int = 1, end: int = 0) -> bool:
    """下载流程：链接/ID -> 保存位置 -> 起止章节(含首尾) -> 下载"""
    try:
        book_id = parse_book_id(spec)
    except ValueError as e:
        print(f"[x] {e}")
        return False

    base = cfg["save_dir"]
    if ask_dir:
        try:
            base = ask("保存位置(回车=默认)", cfg["save_dir"])
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return False
    if ask_range:
        try:
            s = ask("起始章节(回车=第1章)", "1")
            e = ask("结束章节(回车=最后一章)", "")
            start = int(s) if s.strip() else 1
            end = int(e) if e.strip() else 0
            if start < 1:
                start = 1
            if end and end < start:
                print("[!] 结束章节小于起始章节，按单章处理")
                end = start
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return False
    return cmd_download(client, book_id, start, end, Path(base), True,
                        title_hint)


def flow_search(client: Client, cfg: dict) -> None:
    try:
        kw = ask("搜索关键词")
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return
    if not kw:
        print("[i] 未输入关键词")
        return
    divider("-")
    print(f"[i] 搜索《{kw}》...")
    try:
        results = search_books(client, kw)
    except Exception as e:  # noqa: BLE001
        print(f"[x] 搜索失败: {e}")
        return
    if not results:
        print("[x] 没有搜索到相关结果")
        return
    divider("-")
    print(f"共 {len(results)} 个结果：")
    for i, r in enumerate(results, 1):
        status = _status_text(str(r.get("creation_status", "")))
        score = r.get("score") or "-"
        ab = (r.get("abstract") or "").strip().replace("\n", " ")
        print(f"  [{i:>2}] 《{r.get('title')}》  {r.get('author') or ''}")
        print(f"       分类:{r.get('category') or '-'}  状态:{status}  "
              f"评分:{score}")
        print(f"       ID: {r.get('book_id')}")
        if ab:
            print(f"       简介: {ab[:70]}")
        divider("-")
    try:
        sel = ask("选择序号下载(回车取消)")
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return
    if not sel.isdigit() or not (1 <= int(sel) <= len(results)):
        print("[i] 已取消")
        return
    picked = results[int(sel) - 1]
    flow_download(client, cfg, picked["book_id"],
                  title_hint=picked.get("title"))


def flow_batch(client: Client, cfg: dict) -> None:
    try:
        path_s = ask("批量文件路径(每行一个链接/ID)")
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return
    fpath = Path(path_s)
    if not fpath.is_file():
        print(f"[x] 文件不存在: {fpath}")
        return
    lines = [ln.strip() for ln in fpath.read_text(encoding="utf-8",
                                                  errors="ignore").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    if not lines:
        print("[x] 文件为空（或全为注释行）")
        return
    print(f"[i] 共 {len(lines)} 条，开始批量下载...")
    # 统一询问一次起止章节（应用到全部书），回车=全部
    bstart, bend = 1, 0
    try:
        s = ask("起始章节(回车=第1章)", "1")
        e = ask("结束章节(回车=最后一章)", "")
        bstart = int(s) if s.strip() else 1
        bend = int(e) if e.strip() else 0
        if bstart < 1:
            bstart = 1
        if bend and bend < bstart:
            print("[!] 结束章节小于起始章节，按单章处理")
            bend = bstart
    except (EOFError, KeyboardInterrupt):
        print("[i] 使用默认范围（全部章节）")
    ok_n, fail_n = 0, 0
    for i, spec in enumerate(lines, 1):
        divider("=")
        print(f"[{i}/{len(lines)}] {spec[:70]}")
        divider("-")
        try:
            ok = flow_download(client, cfg, spec, ask_dir=False,
                               ask_range=False, start=bstart, end=bend)
        except (EOFError, KeyboardInterrupt):
            print("\n[i] 批量下载中断")
            break
        if ok:
            ok_n += 1
        else:
            fail_n += 1
    divider("=")
    print(f"[批量完成] 成功 {ok_n} 本, 失败 {fail_n} 本")
    divider("=")


def flow_settings(cfg: dict) -> None:
    while True:
        clear_screen()
        divider("=")
        print("    设置")
        divider("-")
        print(f"  [1] 请求间隔: {cfg['delay_min']}~{cfg['delay_max']} 秒")
        print(f"  [2] 默认保存目录: {cfg['save_dir']}")
        print("  [0] 返回")
        divider("-")
        try:
            c = input("  选择: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n返回")
            return
        if c == "1":
            try:
                mi = ask("间隔下限(秒)", str(cfg["delay_min"]))
                ma = ask("间隔上限(秒)", str(cfg["delay_max"]))
                dmin, dmax = float(mi), float(ma)
                if dmax < dmin:
                    raise ValueError
                cfg["delay_min"], cfg["delay_max"] = dmin, dmax
                save_config(cfg)
                print("[ok] 已保存")
            except ValueError:
                print("[x] 输入无效（上限不能小于下限）")
        elif c == "2":
            d = ask("默认保存目录", cfg["save_dir"])
            cfg["save_dir"] = d
            save_config(cfg)
            print("[ok] 已保存")
        else:
            return


def cmd_interactive() -> None:
    cfg = load_config()
    client = Client(cfg["delay_min"], cfg["delay_max"])
    while True:
        clear_screen()
        divider("=")
        print(f"    fanqie-dl v{__version__}  番茄小说下载器")
        print("    交互模式（Ctrl+C 退出）")
        divider("=")
        print(f"    间隔 {cfg['delay_min']}~{cfg['delay_max']}s | "
              f"保存目录: {cfg['save_dir']}")
        divider("-")
        print("  [1] 下载")
        print("  [2] 搜索")
        print("  [3] 批量下载")
        print("  [4] 设置")
        divider("-")
        try:
            c = input("  请选择: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            return

        if c == "1":
            try:
                spec = ask("输入书本ID或分享链接")
            except (EOFError, KeyboardInterrupt):
                print("\n已取消")
                continue
            if spec:
                flow_download(client, cfg, spec)
        elif c == "2":
            flow_search(client, cfg)
        elif c == "3":
            flow_batch(client, cfg)
        elif c == "4":
            flow_settings(cfg)
            cfg = load_config()
            client = Client(cfg["delay_min"], cfg["delay_max"])
        else:
            print("[!] 无效选择")
            continue
        try:
            pause_return()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            return


def main() -> None:
    ap = argparse.ArgumentParser(description="番茄小说下载器 (fanqie-dl)")
    ap.add_argument("book", nargs="?", help=BOOK_ID_HELP)
    ap.add_argument("-i", "--interactive", action="store_true",
                    help="进入交互菜单")
    ap.add_argument("--search", metavar="关键词", help="搜索选书（一条龙）")
    ap.add_argument("--pick", type=int, default=0,
                    help="与--search联用：直接下载第N个结果")
    ap.add_argument("--start", type=int, default=1, help="起始章节（默认1）")
    ap.add_argument("--end", type=int, default=0, help="结束章节（默认全书）")
    ap.add_argument("--meta", action="store_true",
                    help="查看书籍/章节元数据（不下载正文）")
    ap.add_argument("--list", action="store_true", help="仅列出章节")
    ap.add_argument("--cover", action="store_true", help="下载封面图")
    ap.add_argument("--out", default=None, help="输出目录（默认见config.json）")
    ap.add_argument("--delay-min", type=float, default=None,
                    help="请求间隔下限(秒)")
    ap.add_argument("--delay-max", type=float, default=None,
                    help="请求间隔上限(秒)")
    ap.add_argument("--version", action="version",
                    version=f"fanqie-dl {__version__}")
    args = ap.parse_args()

    cfg = load_config()
    if args.delay_min is not None:
        cfg["delay_min"] = args.delay_min
    if args.delay_max is not None:
        cfg["delay_max"] = args.delay_max
    if args.delay_min is not None or args.delay_max is not None:
        if cfg["delay_max"] < cfg["delay_min"]:
            print("[x] --delay-max 不能小于 --delay-min")
            sys.exit(1)
        save_config(cfg)
    out_dir = Path(args.out) if args.out else Path(cfg["save_dir"])

    # 交互模式：无参数 或 -i
    if args.interactive or (not args.book and not args.search):
        cmd_interactive()
        return

    client = Client(cfg["delay_min"], cfg["delay_max"])

    if args.search:
        try:
            results = search_books(client, args.search)
        except Exception as e:  # noqa: BLE001
            print(f"[x] 搜索失败: {e}")
            sys.exit(1)
        if not results:
            print("[x] 没有搜索到相关结果")
            sys.exit(1)
        print(f"共 {len(results)} 个结果：")
        for i, r in enumerate(results, 1):
            status = _status_text(str(r.get("creation_status", "")))
            print(f"  {i:>2}. 《{r.get('title')}》 {r.get('author') or ''} "
                  f"[{r.get('category') or ''}] {status} 评分{r.get('score') or '-'}")
            print(f"      ID: {r.get('book_id')}")
        if args.pick:
            idx = args.pick
        else:
            try:
                inp = input("输入序号下载该书（回车退出）: ").strip()
                idx = int(inp) if inp else 0
            except (EOFError, KeyboardInterrupt):
                idx = 0
        if not (1 <= idx <= len(results)):
            print("已取消。")
            return
        picked = results[idx - 1]
        print(f"\n下载《{picked.get('title')}》 (ID={picked.get('book_id')})")
        cmd_download(client, picked["book_id"], args.start, args.end,
                     out_dir, args.cover, picked.get("title"))
        return

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
        print("[x] 未获取到章节（可能书不存在或需登录）")
        sys.exit(1)
    if args.list:
        cmd_list(novel)
        return
    cmd_download(client, book_id, args.start, args.end, out_dir, args.cover)


if __name__ == "__main__":
    main()
