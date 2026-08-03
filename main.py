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
from datetime import datetime
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
from fanqie.record import (load_record, merge_orders, new_record,
                           save_record, scan_records)
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


def _existing_titles(out_path: Path) -> set:
    """已写入文件中的章节标题（去重用）"""
    titles = set()
    if out_path.is_file():
        try:
            text = out_path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith(("〔", "=", "《", "作者", "标签",
                                                  "状态", "总字数", "阅读量",
                                                  "最新章节", "最近更新",
                                                  "章节数", "封面", "简介",
                                                  "书ID", "目录", "更新",
                                                  "ID:", "保存")):
                    titles.add(line)
        except OSError:
            pass
    return titles


def _write_chapter(out_fh, ch, idx: int, content: str, word_count: int | None,
                   chapter_by_id: dict) -> None:
    cm = chapter_by_id.get(ch["itemId"])
    pub = fmt_time(cm.publish_time, "%Y-%m-%d") if cm else "未知"
    words = f"{word_count:,}字" if word_count else "未知"
    out_fh.write(f"\n\n{ch['title']}\n"
                 f"〔字数:{words} | 更新:{pub}〕\n\n{content}\n")
    out_fh.flush()


def _download_sequential(client: Client, items: list, out_fh,
                         chapter_by_id: dict) -> tuple:
    """单线程顺序下载；返回 (ok, preview_skipped, failed, new_orders)"""
    from tqdm import tqdm as _tqdm
    ok = preview = 0
    failed: list = []
    new_orders: list = []
    referer = None
    prog = _tqdm(total=len(items), unit="章", ncols=70)
    for idx, order, ch in items:
        try:
            content, wc = download_chapter_with_info(client, ch["itemId"],
                                                     referer)
            referer = f"https://fanqienovel.com/reader/{ch['itemId']}"
            if not content:
                preview += 1
                print(f"\n[!] 第{idx}章《{ch['title']}》疑似预览/付费，跳过")
            else:
                _write_chapter(out_fh, ch, idx, content, wc, chapter_by_id)
                ok += 1
                new_orders.append(order)
        except Exception as e:  # noqa: BLE001
            failed.append((idx, ch["title"], str(e)))
            print(f"\n[x] 第{idx}章《{ch['title']}》失败: {e}")
        prog.update(1)
    prog.close()
    return ok, preview, failed, new_orders


def cmd_download(client: Client, book_id: str, start: int, end: int,
                 base_dir: Path, with_cover: bool = True,
                 title_hint: str | None = None,
                 append: bool = False, known_orders: list | None = None,
                 override_dir: Path | None = None,
                 threads: int = 1) -> bool:
    """下载一本书到 base_dir/<书名>/ 目录（TXT + 封面 + JSON 记录）

    - 章节去重：记录中的已下章节 / 文件内已有标题 自动跳过
    - 多线程：threads>1 时每线程独立指纹/UA/cookie，章节按序写入
    - 失败章节写入 <书名>_failed.txt，不中断整体下载
    """
    from fanqie.pool import download_parallel, make_workers

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
    book_dir = override_dir or (base_dir / safe)
    book_dir.mkdir(parents=True, exist_ok=True)
    out_path = book_dir / f"{safe}.txt"
    divider("-")
    print(f"《{novel.title}》 共 {total} 章，下载 [{start}~{end}] 共 {len(sel)} 章")
    print(f"保存目录: {book_dir}")
    if threads > 1:
        print(f"线程数: {threads}（每线程独立指纹/UA）")
    divider("-")

    try:
        meta = build_meta(client, book_id)
    except Exception:  # noqa: BLE001
        meta = None
    header = render_summary(meta) if meta else f"《{novel.title}》"
    chapter_by_id = {c.item_id: c for c in meta.chapters} if meta else {}

    # 去重：记录中的已下章节序号 + 文件内已有章节标题
    record = load_record(book_dir, safe)
    existing_orders = set(
        int(o) for o in (known_orders or record.get("downloaded_orders", []))
        if str(o).isdigit())
    existing_titles = _existing_titles(out_path)
    to_download = []
    for idx, ch in enumerate(sel, start):
        order = int(ch.get("realChapterOrder") or idx)
        if order in existing_orders or ch["title"] in existing_titles:
            print(f"[i] 第{idx}章《{ch['title']}》已存在，跳过（去重）")
            continue
        to_download.append((idx, order, ch))
    if not to_download:
        print("[i] 没有需要下载的章节（已全部存在）")
        return True

    ok = preview = 0
    failed: list = []
    new_orders: list = []
    t0 = time.time()
    # 文件已存在 → 追加（保留旧内容）；全新文件 → 新建并写头部
    mode = "a" if (append or out_path.is_file()) else "w"
    with open(out_path, mode, encoding="utf-8") as f:
        if mode == "w":
            f.write(header + "\n\n")
            f.write("=" * 40 + "\n")
        if threads > 1:
            workers = make_workers(threads, client.pacing.delay_min,
                                   client.pacing.delay_max)
            ok, preview, failed, new_orders = download_parallel(
                workers, to_download, f, chapter_by_id, _write_chapter)
        else:
            ok, preview, failed, new_orders = _download_sequential(
                client, to_download, f, chapter_by_id)

    # 失败章节单独记录
    if failed:
        failed_path = book_dir / f"{safe}_failed.txt"
        with open(failed_path, "a", encoding="utf-8") as ff:
            ff.write(f"== {datetime.now():%Y-%m-%d %H:%M:%S} "
                     f"本次失败 {len(failed)} 章 ==\n")
            for idx, title, err in failed:
                ff.write(f"第{idx}章 {title}: {err}\n")
        print(f"\n[失败记录] {failed_path}（{len(failed)} 章）")

    # 封面
    cover_path = None
    if with_cover and meta and meta.cover_url:
        cover_path = book_dir / f"{safe}_cover.jpg"
        if save_cover(client, meta.cover_url, cover_path):
            print(f"\n[ok] 封面已保存: {cover_path}")
        else:
            cover_path = None
            print("\n[!] 封面下载失败（URL 可能已过期）")

    # 更新下载记录 JSON（合并历史记录 + 本次新增）
    rec = new_record(book_id, novel.title, meta.status if meta else "未知")
    rec["downloaded_orders"] = merge_orders(
        rec, record.get("downloaded_orders", []))
    rec["downloaded_orders"] = merge_orders(rec, known_orders or [])
    rec["downloaded_orders"] = merge_orders(rec, new_orders)
    rec_path = save_record(book_dir, safe, rec)
    print(f"\n[记录] {rec_path}  (已下载 {len(rec['downloaded_orders'])} 章)")

    cost = time.time() - t0
    print(f"[完成] 成功 {ok} 章, 跳过 {preview}, 失败 {len(failed)}, "
          f"耗时 {cost:.0f}s")
    print(f"[文件] {out_path}")
    if cover_path:
        print(f"[封面] {cover_path}")
    if failed:
        print(f"[提示] 失败章节见 {safe}_failed.txt，可缩小范围重试")
    return len(failed) == 0



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
                        title_hint, threads=cfg.get("threads", 1))


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
        sel = ask("选择序号下载(回车=第1个)", "1")
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return
    if not sel.isdigit() or not (1 <= int(sel) <= len(results)):
        print("[i] 序号无效，已取消")
        return
    picked = results[int(sel) - 1]
    flow_download(client, cfg, picked["book_id"],
                  title_hint=picked.get("title"))


def flow_update(client: Client, cfg: dict) -> None:
    """连载下载更新：扫描连载中书籍 -> 多选 -> 校验规则 -> 追加新章节"""
    base = Path(cfg["save_dir"])
    records = [r for r in scan_records(base) if r.get("status") == "连载中"]
    if not records:
        print("[i] 下载目录中没有标记为[连载中]的书籍")
        return
    divider("-")
    print(f"发现 {len(records)} 本连载中书籍：")
    for i, r in enumerate(records, 1):
        n = len(r.get("downloaded_orders", []) or [])
        print(f"  [{i}] 《{r.get('title')}》 已下载 {n} 章")
    divider("-")
    try:
        sel = ask("选择序号(半角逗号分隔，回车=全部)", "")
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return
    if sel.strip():
        idxs = [int(p) for p in sel.replace("，", ",").split(",")
                if p.strip().isdigit()]
        if not idxs:
            print("[x] 序号无效")
            return
    else:
        idxs = list(range(1, len(records) + 1))

    ok_n, fail_n = 0, 0
    for i in idxs:
        if not (1 <= i <= len(records)):
            print(f"[!] 跳过无效序号 {i}")
            continue
        try:
            ok = update_one(client, cfg, records[i - 1])
        except (EOFError, KeyboardInterrupt):
            print("\n[i] 连载更新中断")
            break
        if ok:
            ok_n += 1
        else:
            fail_n += 1
    divider("=")
    print(f"[连载更新完成] 成功 {ok_n} 本, 失败 {fail_n} 本")
    divider("=")


def update_one(client: Client, cfg: dict, rec: dict) -> bool:
    """更新单本书：校验规则 -> 只下新章节 -> 追加到旧文件末尾"""
    divider("=")
    print(f"更新《{rec.get('title')}》 (ID={rec.get('book_id')})")
    orders = sorted(rec.get("downloaded_orders", []) or [])
    # 规则校验：必须从第1章开始且连续
    if orders != list(range(1, len(orders) + 1)):
        print("[x] 已下载章节不连续（未从第1章开始或中间缺章），"
              "请先用 [1] 下载补全")
        return False
    try:
        novel = get_book(client, rec["book_id"])
    except Exception as e:  # noqa: BLE001
        print(f"[x] 获取目录失败: {e}")
        return False
    total = len(novel.chapters)
    # 规则校验：未下载到最后一章
    if len(orders) >= total:
        print(f"[i] 已是最新（共 {total} 章），无需更新")
        return False
    print(f"[i] 发现新章节 {len(orders) + 1}~{total} 共 {total - len(orders)} 章")
    return cmd_download(
        client, rec["book_id"], len(orders) + 1, total,
        Path(cfg["save_dir"]), with_cover=False,
        title_hint=rec.get("title"), append=True,
        known_orders=orders,
        override_dir=rec["_dir"],
        threads=cfg.get("threads", 1),
    )


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
        print(f"  [3] 下载线程数: {cfg.get('threads', 1)} (1~10)")
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
        elif c == "3":
            t = ask("下载线程数(1~10)", str(cfg.get("threads", 1)))
            try:
                n = int(t)
                if not 1 <= n <= 10:
                    raise ValueError
                cfg["threads"] = n
                save_config(cfg)
                print("[ok] 已保存")
            except ValueError:
                print("[x] 请输入 1~10 的整数")
        else:
            return


def cmd_interactive() -> None:
    cfg = load_config()
    client = Client(cfg["delay_min"], cfg["delay_max"])
    while True:
        clear_screen()
        divider("=")
        print(f"    fanqie-dl v{__version__}  番茄小说下载器")
        divider("=")
        print(f"    间隔 {cfg['delay_min']}~{cfg['delay_max']}s | "
              f"保存目录: {cfg['save_dir']}")
        divider("-")
        print("  [1] 下载")
        print("  [2] 搜索")
        print("  [3] 连载下载更新")
        print("  [4] 批量下载")
        print("  [5] 设置")
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
            flow_update(client, cfg)
        elif c == "4":
            flow_batch(client, cfg)
        elif c == "5":
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
    ap.add_argument("--threads", type=int, default=None,
                    help="下载线程数(1~10)，>1 时每线程独立指纹/UA")
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
    if args.threads is not None:
        if not 1 <= args.threads <= 10:
            print("[x] --threads 需在 1~10 之间")
            sys.exit(1)
        cfg["threads"] = args.threads
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
                inp = input("输入序号下载该书（回车=第1个）: ").strip()
                idx = int(inp) if inp else 1
            except (EOFError, KeyboardInterrupt):
                idx = 1
        if not (1 <= idx <= len(results)):
            print("序号无效。")
            return
        picked = results[idx - 1]
        print(f"\n下载《{picked.get('title')}》 (ID={picked.get('book_id')})")
        cmd_download(client, picked["book_id"], args.start, args.end,
                     out_dir, args.cover, picked.get("title"),
                     threads=cfg.get("threads", 1))
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
    cmd_download(client, book_id, args.start, args.end, out_dir, args.cover,
                 threads=cfg.get("threads", 1))


if __name__ == "__main__":
    main()
