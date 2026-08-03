# -*- coding: utf-8 -*-
"""多线程章节下载

- 每线程一个独立 Client：TLS 指纹、UA、匿名 cookie 各不相同
- 章节按顺序写入文件（结果经重排缓冲，保证 TXT 章节顺序不乱）
- 失败章节单独收集，不中断整体下载
"""
import queue
from concurrent.futures import ThreadPoolExecutor

from tqdm import tqdm

from .downloader import IMPERSONATE_TARGETS, Client, download_chapter_with_info


def make_workers(n: int, delay_min: float, delay_max: float) -> list:
    """创建 n 个身份互异的客户端（指纹轮换 + 各自随机 UA/cookie）"""
    clients = []
    n_targets = len(IMPERSONATE_TARGETS)
    for i in range(n):
        clients.append(Client(
            delay_min, delay_max,
            impersonate=IMPERSONATE_TARGETS[i % n_targets],
        ))
    return clients


def download_parallel(clients: list, items: list, out_fh,
                      chapter_by_id: dict, write_chapter) -> tuple:
    """并发下载章节并按顺序写入 out_fh（仅写线程触碰文件）

    items: list[(idx, order, ch)]
    返回: (ok, preview_skipped, failed_list, new_orders)
    """
    total = len(items)
    work_q = queue.Queue()
    for it in items:
        work_q.put(it)
    result_q = queue.PriorityQueue()  # (order, idx, ch, content, wc, err)

    def worker(cli: Client) -> None:
        while True:
            try:
                idx, order, ch = work_q.get_nowait()
            except queue.Empty:
                return
            try:
                content, wc = download_chapter_with_info(cli, ch["itemId"])
                result_q.put((order, idx, ch, content, wc, None))
            except Exception as e:  # noqa: BLE001
                result_q.put((order, idx, ch, None, None, str(e)))

    buf = {}
    next_order = items[0][1]
    done = ok = preview = 0
    failed: list = []
    new_orders: list = []
    prog = tqdm(total=total, unit="章", ncols=70)

    with ThreadPoolExecutor(max_workers=len(clients)) as ex:
        for cli in clients:
            ex.submit(worker, cli)
        while done < total:
            order, idx, ch, content, wc, err = result_q.get()
            buf[order] = (idx, ch, content, wc, err)
            while next_order in buf:
                idx, ch, content, wc, err = buf.pop(next_order)
                if err:
                    failed.append((idx, ch["title"], err))
                    print(f"\n[x] 第{idx}章《{ch['title']}》失败: {err}")
                elif content:
                    write_chapter(out_fh, ch, idx, content, wc, chapter_by_id)
                    ok += 1
                    new_orders.append(next_order)
                else:
                    preview += 1
                    print(f"\n[!] 第{idx}章《{ch['title']}》疑似预览/付费，跳过")
                done += 1
                prog.update(1)
                next_order += 1
    prog.close()
    return ok, preview, failed, new_orders


__all__ = ["make_workers", "download_parallel"]
