# -*- coding: utf-8 -*-
"""本地配置持久化（config.json，位于项目根目录）"""
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

DEFAULTS = {
    "delay_min": 1.0,     # 请求间隔下限（秒）
    "delay_max": 3.0,     # 请求间隔上限（秒）
    "save_dir": "books",  # 默认保存目录
    "threads": 1,         # 下载线程数（1~10，>1 时每线程独立指纹/UA）
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        for k in DEFAULTS:
            if k in data:
                cfg[k] = data[k]
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    data = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


__all__ = ["load_config", "save_config", "DEFAULTS"]
