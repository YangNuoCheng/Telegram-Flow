"""Telegram 接入：会话、来源同步、消息缓存与限流处理。"""
from __future__ import annotations

import asyncio
import json
import math
import re
import sqlite3
import time
from collections import OrderedDict

from aiohttp import web
from telethon import TelegramClient, errors, utils
from telethon.tl.types import (
    DocumentAttributeAnimated,
    DocumentAttributeVideo,
    InputMessagesFilterPhotoVideo,
)

from .config import CONFIG, SESSION, SYNC_BATCH, SYNC_EVERY
from .features import tokens
from .filters import refresh_filters
from .storage import blocklist, db

INVITE = re.compile(r"(?:t\.me/\+|t\.me/joinchat/|^\+)([\w-]+)")


class Telegram:
    def __init__(self) -> None:
        self.client: TelegramClient | None = None
        self.ready = False
        self.messages: OrderedDict[tuple[int, int], object] = OrderedDict()
        self.syncing: str = ""
        self.older_pending = False
        self.retry_until = 0.0
        self.lookup_lock = asyncio.Lock()
        self.message_tasks: dict[tuple[int, int], asyncio.Task] = {}

    async def start(self) -> None:
        if not CONFIG.exists():
            return
        cfg = json.loads(CONFIG.read_text())
        self.client = TelegramClient(str(SESSION), int(cfg["api_id"]), cfg["api_hash"], flood_sleep_threshold=0)
        await self.client.connect()
        self.ready = await self.client.is_user_authorized()

    def retry_after(self) -> int:
        return max(0, math.ceil(self.retry_until - time.time()))

    def limited(self, seconds: int | None = None):
        if seconds is not None:
            self.retry_until = max(self.retry_until, time.time() + seconds)
        return web.HTTPTooManyRequests(headers={"Retry-After": str(self.retry_after())}, text="Telegram 请求限流，等待后重试")

    def cache_message(self, chat: int, m) -> None:
        self.messages[(chat, m.id)] = m
        self.messages.move_to_end((chat, m.id))
        while len(self.messages) > 6000:
            self.messages.popitem(last=False)

    async def fetch_messages(self, chat: int, ids):
        async with self.lookup_lock:
            if self.retry_after():
                raise self.limited()
            try:
                return await self.client.get_messages(chat, ids=ids)
            except errors.FloodWaitError as e:
                raise self.limited(e.seconds) from e

    async def message(self, chat_id: int, msg_id: int):
        key = (chat_id, msg_id)
        if key in self.messages:
            self.messages.move_to_end(key)
            return self.messages[key]
        if self.retry_after():
            raise self.limited()
        if key not in self.message_tasks:
            async def load():
                msg = await self.fetch_messages(chat_id, msg_id)
                if msg is None or msg.media is None:
                    raise web.HTTPNotFound()
                self.cache_message(chat_id, msg)
                return msg
            task = self.message_tasks[key] = asyncio.create_task(load())
            def finished(t):
                self.message_tasks.pop(key, None)
                if not t.cancelled():
                    t.exception()
            task.add_done_callback(finished)
        return await asyncio.shield(self.message_tasks[key])

    async def dialogs(self) -> list[dict]:
        """刷新账号已加入的频道和群组。首次导入之后新出现的频道自动勾选；群组、取消过勾选的来源，
        以及标题命中过滤词表（含默认的未成年、偷拍等词）的频道都不自动勾选。"""
        out = []
        async for d in self.client.iter_dialogs():
            if not (d.is_channel or d.is_group):
                continue
            ent = d.entity
            out.append({"id": utils.get_peer_id(ent), "title": d.name or "", "username": getattr(ent, "username", None),
                        "kind": "channel" if d.is_channel and not d.is_group else "group"})
        with db() as c:
            known = {r[0] for r in c.execute("SELECT id FROM channel")}
            blocked = blocklist()
            for d in out:
                title = d["title"].casefold()
                auto = int(bool(known) and d["id"] not in known and d["kind"] == "channel"
                           and not any(w in title for w in blocked))
                c.execute("INSERT INTO channel(id,title,username,kind,selected) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                          "title=excluded.title, username=excluded.username, kind=excluded.kind",
                          (d["id"], d["title"], d["username"], d["kind"], auto))
                d["new"] = bool(auto)
        return out

    async def refresh_dialogs(self) -> None:
        """后台检查新加入的频道；有新频道就立即同步。失败只记录，不影响常规同步。"""
        if not self.ready or self.retry_after():
            return
        try:
            new = [d for d in await self.dialogs() if d["new"]]
        except errors.FloodWaitError as e:
            self.limited(e.seconds)
            return
        except Exception as exc:
            print(f"刷新频道列表失败: {exc}")
            return
        if new:
            print("自动加入内容流: " + "、".join(d["title"] for d in new))

    async def sync_channel(self, ch: sqlite3.Row, older: bool = False) -> int:
        block = blocklist()
        kwargs = {"limit": SYNC_BATCH, "filter": InputMessagesFilterPhotoVideo()}
        if older and ch["oldest_msg_id"]:
            kwargs["offset_id"] = ch["oldest_msg_id"]
        # 不加 min_id：每轮重取最近一批，顺便刷新点赞数和评论数
        rows, texts = [], {}
        async for m in self.client.iter_messages(ch["id"], **kwargs):
            row = describe(m)
            if row:
                self.cache_message(ch["id"], m)
                rows.append(row)
                if m.grouped_id and m.message:
                    texts[m.grouped_id] = m.message
        if not rows:
            return 0
        with db() as c:
            for r in rows:
                text = r["text"] or texts.get(r["grouped_id"], "")
                feats = tokens(text) + [f"kind:{r['kind']}"] + ([f"dur:{duration_bucket(r['duration'])}"] if r["duration"] else [])
                blocked = int(any(b in text.casefold() for b in block))
                gkey = f"{ch['id']}:{r['grouped_id'] or r['msg_id']}"
                c.execute("INSERT OR IGNORE INTO item(chat_id,msg_id,gkey,date,text,kind,duration,size,mime,width,height,features,blocked) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (ch["id"], r["msg_id"], gkey, r["date"], text, r["kind"], r["duration"], r["size"], r["mime"],
                           r["width"], r["height"], json.dumps(feats, ensure_ascii=False), blocked))
                c.execute("UPDATE item SET reactions=?, replies=? WHERE chat_id=? AND msg_id=?",
                          (r["reactions"], r["replies"], ch["id"], r["msg_id"]))
            ids = [r["msg_id"] for r in rows]
            c.execute("UPDATE channel SET last_msg_id=MAX(last_msg_id,?), oldest_msg_id=CASE WHEN oldest_msg_id=0 THEN ? ELSE MIN(oldest_msg_id,?) END, synced_at=? WHERE id=?",
                      (max(ids), min(ids), min(ids), time.time(), ch["id"]))
        return len(rows)

    async def sync_all(self, older: bool = False) -> None:
        if not self.ready or self.retry_after():
            return
        if self.syncing:
            self.older_pending |= older
            return
        with db() as c:
            chans = c.execute("SELECT * FROM channel WHERE selected=1").fetchall()
        try:
            for ch in chans:
                with db() as c:  # 同步途中可能被取消勾选或退出
                    ch = c.execute("SELECT * FROM channel WHERE id=? AND selected=1", (ch["id"],)).fetchone()
                if ch is None:
                    continue
                self.syncing = ch["title"]
                try:
                    await self.sync_channel(ch, older)
                except errors.FloodWaitError as e:
                    self.limited(e.seconds)
                    return
                except Exception as exc:  # 单个频道失败不影响其他频道
                    print(f"同步失败 {ch['title']}: {exc}")
                await asyncio.sleep(2)
        finally:
            self.syncing = ""
            refresh_filters()
            if self.older_pending:
                self.older_pending = False
                asyncio.create_task(self.sync_all(older=True))

    async def loop(self) -> None:
        while True:
            await self.refresh_dialogs()
            await self.sync_all()
            await asyncio.sleep(SYNC_EVERY)


def duration_bucket(secs: float) -> str:
    for edge, name in ((15, "<15s"), (60, "<1m"), (300, "<5m"), (1200, "<20m"), (3600, "<1h")):
        if secs < edge:
            return name
    return "1h+"


def describe(m) -> dict | None:
    base = {"msg_id": m.id, "date": m.date.timestamp(), "text": m.message or "", "grouped_id": m.grouped_id,
            "duration": None, "size": None, "mime": None, "width": None, "height": None,
            "reactions": sum(r.count for r in m.reactions.results) if getattr(m, "reactions", None) else 0,
            "replies": m.replies.replies if getattr(m, "replies", None) else 0}
    if m.photo:
        size = max((s for s in m.photo.sizes if hasattr(s, "w")), key=lambda s: s.w * s.h, default=None)
        return {**base, "kind": "photo", "width": getattr(size, "w", None), "height": getattr(size, "h", None)}
    doc = m.document
    if doc is None:
        return None
    video = next((a for a in doc.attributes if isinstance(a, DocumentAttributeVideo)), None)
    if video is None:
        return None
    animated = any(isinstance(a, DocumentAttributeAnimated) for a in doc.attributes)
    return {**base, "kind": "gif" if animated else "video", "duration": video.duration, "size": doc.size,
            "mime": doc.mime_type, "width": video.w, "height": video.h}


TG = Telegram()
