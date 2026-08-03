# -*- coding: utf-8 -*-
"""请求节奏控制：随机延迟（抖动）+ 指数退避

模拟人类阅读/翻页的自然节奏，避免被频率检测（429）封控。
"""
import random
import time
from datetime import datetime


class Pacing:
    """随机延迟调度器：每次请求之间随机等待 delay_min~delay_max 秒"""

    def __init__(self, delay_min: float = 1.0, delay_max: float = 3.0):
        self.delay_min = max(0.0, delay_min)
        self.delay_max = max(self.delay_min, delay_max)

    def wait(self) -> None:
        """请求前等待（含随机抖动，避免固定间隔特征）"""
        if self.delay_max <= 0:
            return
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    def __repr__(self) -> str:  # pragma: no cover
        return (f"Pacing(delay={self.delay_min}~{self.delay_max}s)")


def backoff_sleep(attempt: int, base: float = 2.0, cap: float = 30.0,
                  retry_after: float | None = None) -> None:
    """失败后的退避等待。

    - 服务器返回 Retry-After 时优先遵循（但不超过 cap）
    - 否则按 指数退避 + 随机抖动：base * 2^attempt + U(0,1)
    """
    if retry_after and retry_after > 0:
        wait = min(float(retry_after), cap)
    else:
        wait = min(base * (2 ** attempt) + random.uniform(0, 1), cap)
    time.sleep(wait)


def parse_retry_after(value: str | None, fallback: float = 10.0) -> float:
    """解析 Retry-After 响应头（秒数或 HTTP 日期）"""
    if not value:
        return fallback
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        # HTTP-date 格式（如 Wed, 21 Oct 2015 07:28:00 GMT）
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(value)
        return max(0.0, (dt - datetime.now(tz=dt.tzinfo)).total_seconds())
    except Exception:  # noqa: BLE001
        return fallback
