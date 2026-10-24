"""路径、端口与同步参数。私有数据都在仓库根目录的 data/ 下。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
DATA = ROOT / "data"
DB = DATA / "feed.db"
CONFIG = DATA / "config.json"
SESSION = DATA / "telegram"
BLOCKLIST = DATA / "blocklist.txt"
PORT = int(os.environ.get("TG_FEED_PORT", "8978"))
SYNC_BATCH = 200            # 每个频道每轮最多取多少条图片/视频消息
SYNC_EVERY = 15 * 60        # 后台同步间隔（秒）
CHUNK = 512 * 1024
DEFAULT_BLOCK = ["未成年", "幼女", "萝莉", "蘿莉", "ロリ", "loli", "lolita", "小学生", "中学生", "初中生", "儿童", "child", "underage", "偷拍", "盗撮", "upskirt", "revenge"]
