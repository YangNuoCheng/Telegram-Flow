"""Web 服务：页面、API 路由、设备访问认证与启动入口。"""
from __future__ import annotations

import asyncio
import contextlib
import io
import ipaddress
import os
import re
import secrets
import socket
import time
from pathlib import Path

import segno
from aiohttp import web
from telethon import errors, functions, types, utils

from .config import CONFIG, DATA, PORT, WEB
from .features import card_features, flabel
from .filters import refresh_filters
from .learning import engagement, median_dwell, update
from .media import ext_image, image, pages, prefetch, video
from .ranking import WINDOW, feed
from .storage import db, init_storage
from .telegram import INVITE, TG

# ---------- HTTP ----------

async def index(_req):
    return web.FileResponse(WEB / "index.html")


async def about(_req):
    return web.FileResponse(WEB / "about.html")


async def architecture(_req):
    return web.FileResponse(WEB / "architecture.svg")


async def status(_req):
    with db() as c:
        n = c.execute("SELECT COUNT(DISTINCT gkey) FROM item i JOIN channel ch ON ch.id=i.chat_id WHERE ch.selected=1 AND blocked=0").fetchone()[0]
        chans = c.execute("SELECT COUNT(*) FROM channel WHERE selected=1").fetchone()[0]
        learned = c.execute("SELECT COUNT(*) FROM event WHERE kind!='impression'").fetchone()[0]
    return web.json_response({"configured": CONFIG.exists(), "ready": TG.ready, "syncing": TG.syncing,
                              "cards": n, "channels": chans, "signals": learned, "retry_after": TG.retry_after()})


async def channels(_req):
    await TG.dialogs()
    with db() as c:
        rows = [dict(r) for r in c.execute("SELECT id,title,username,kind,selected,synced_at FROM channel ORDER BY selected DESC, title")]
    return web.json_response(rows)


async def select_channels(req):
    body = await req.json()
    ids = [int(i) for i in body.get("ids", [])]
    with db() as c:
        c.execute("UPDATE channel SET selected=0")
        c.executemany("UPDATE channel SET selected=1 WHERE id=?", [(i,) for i in ids])
    asyncio.create_task(TG.sync_all())
    return web.json_response({"selected": len(ids)})


async def more(_req):
    asyncio.create_task(TG.sync_all(older=True))
    return web.json_response({"ok": True})




def clean_ref(ref: str) -> str:
    ref = ref.strip().rstrip("/")
    ref = re.sub(r"^(https?://)?(www\.)?(t\.me|telegram\.me)/(s/)?", "t.me/", ref)
    if ref.startswith("t.me/") and not INVITE.search(ref):
        ref = ref[5:].split("/")[0].split("?")[0]
    return ref.lstrip("@")


async def peek_one(ref: str) -> dict:
    ref = clean_ref(ref)
    m = INVITE.search(ref)
    if m:
        inv = await TG.client(functions.messages.CheckChatInviteRequest(m.group(1)))
        chat = getattr(inv, "chat", None)
        if chat is not None:  # 已经是成员
            full = await TG.client(functions.channels.GetFullChannelRequest(chat))
            return {"ref": ref, "title": chat.title, "username": getattr(chat, "username", None),
                    "count": full.full_chat.participants_count, "joined": not getattr(chat, "left", False)}
        return {"ref": ref, "title": inv.title, "username": None, "count": inv.participants_count, "joined": False}
    ent = await TG.client.get_entity(ref)
    if not isinstance(ent, types.Channel):
        raise ValueError("不是频道或群组")
    full = await TG.client(functions.channels.GetFullChannelRequest(ent))
    uname = ent.username or next((u.username for u in (ent.usernames or []) if u.active), None)
    return {"ref": ref, "title": ent.title, "username": uname,
            "count": full.full_chat.participants_count, "joined": not ent.left}


async def peek(req):
    refs = [r for r in re.split(r"[\s,，]+", req.rel_url.query.get("ref", "")) if r][:30]
    out = []
    for r in refs:
        try:
            out.append(await peek_one(r))
        except errors.FloodWaitError as e:
            out.append({"ref": r, "error": f"Telegram 限流，{e.seconds} 秒后再查（剩下的先不查）"})
            break
        except Exception as e:  # 用户名不存在、链接失效等，逐条报给前端
            out.append({"ref": r, "error": str(e)[:120]})
    return web.json_response(out)


async def join(req):
    ref = clean_ref((await req.json()).get("ref", ""))
    m = INVITE.search(ref)
    try:
        if m:
            res = await TG.client(functions.messages.ImportChatInviteRequest(m.group(1)))
            ent = res.chats[0]
        else:
            ent = await TG.client.get_entity(ref)
            await TG.client(functions.channels.JoinChannelRequest(ent))
    except errors.FloodWaitError as e:
        return web.json_response({"error": f"Telegram 限流，{e.seconds} 秒后再试"}, status=429)
    except errors.UserAlreadyParticipantError:
        ent = await TG.client.get_entity(ref) if not m else None
    except Exception as e:
        return web.json_response({"error": str(e)[:160]}, status=400)
    await TG.dialogs()
    if ent is not None:
        with db() as c:
            c.execute("UPDATE channel SET selected=1 WHERE id=?", (utils.get_peer_id(ent),))
            row = c.execute("SELECT * FROM channel WHERE id=?", (utils.get_peer_id(ent),)).fetchone()
        if row:
            asyncio.create_task(TG.sync_channel(row))
    return web.json_response({"ok": True})


async def get_feed(req):
    q = await req.json() if req.method == "POST" else req.rel_url.query
    excluded = q.get("exclude", [])
    exclude = set(filter(None, excluded.split(",") if isinstance(excluded, str) else excluded))
    history = q.get("recent", [])
    recent = [c for c in (history.split(",") if isinstance(history, str) else history) if c][-WINDOW:]
    size = max(1, min(200, int(q.get("size", 8))))
    media_history = q.get("recentMedia", [])
    if not isinstance(media_history, list):
        media_history = []
    cards = feed(q.get("mode", "foryou"), q.get("feature") or None, exclude, size=size, recent=recent,
                 recent_media=media_history[-WINDOW:])
    return web.json_response(cards)


async def event(req):
    body = await req.json()
    key, kind = body["key"], body["kind"]
    value = float(body.get("ms", 0))
    with db() as c:
        rows = c.execute("SELECT * FROM item WHERE gkey=?", (key,)).fetchall()
        if not rows:
            raise web.HTTPNotFound()
        c.execute("INSERT INTO event(gkey,kind,value,at) VALUES(?,?,?,?)", (key, kind, value, time.time()))
        is_video = any(r["kind"] != "photo" for r in rows)
        typical = 0.0
        if kind == "dwell":
            vals = [r[0] / 1000 for r in c.execute(
                "SELECT e.value FROM event e WHERE e.kind='dwell' AND e.id < (SELECT MAX(id) FROM event) AND "
                "EXISTS(SELECT 1 FROM item i WHERE i.gkey=e.gkey AND (i.kind!='photo')=?) ORDER BY e.id DESC LIMIT 200", (int(is_video),))][::-1]
            typical = median_dwell(vals, is_video)
        y = engagement(kind, value, is_video, typical)
        if y is not None:
            update(c, card_features(rows), y)
    return web.json_response({"ok": True})


async def taste(_req):
    with db() as c:
        rows = c.execute("SELECT feature,w,n FROM weight WHERE n>=2 AND feature!='bias' AND feature NOT LIKE 'kind:%' AND feature NOT LIKE 'dur:%' ORDER BY w DESC").fetchall()
        names = {f"ch:{r['id']}": r["title"] for r in c.execute("SELECT id,title FROM channel")}
    fmt = lambda r: {"feature": r["feature"], "label": flabel(r["feature"], names), "w": round(r["w"], 2), "n": r["n"]}
    singles = [r for r in rows if not r["feature"].startswith("x:")]
    pairs = [r for r in rows if r["feature"].startswith("x:") and r["n"] >= 3]
    return web.json_response({"top": [fmt(r) for r in singles[:20]], "combos": [fmt(r) for r in pairs[:15]],
                              "bottom": [fmt(r) for r in singles[::-1][:10] if r["w"] < 0]})



async def leave(req):
    chat = int((await req.json())["id"])
    try:
        await TG.client.delete_dialog(chat)  # 频道/群组：退出
    except Exception as e:
        return web.json_response({"error": str(e)[:160]}, status=400)
    with db() as c:
        c.execute("DELETE FROM item WHERE chat_id=?", (chat,))
        c.execute("DELETE FROM channel WHERE id=?", (chat,))
    return web.json_response({"ok": True})



TAILNET = ipaddress.ip_network("100.64.0.0/10")
TOKEN_FILE = DATA / "access_token"


def access_token() -> str:
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(18))
        with contextlib.suppress(OSError):  # Windows 挂载目录可能不支持
            TOKEN_FILE.chmod(0o600)
    return TOKEN_FILE.read_text().strip()


def lan_ip() -> str | None:
    configured = os.environ.get("TG_FEED_LAN_IP", "").strip()
    if configured:
        return str(ipaddress.IPv4Address(configured))
    if Path("/.dockerenv").exists():
        return None
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # UDP connect 不发包，只用来问系统走哪块网卡
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


async def lan(req):
    """给电脑上的「手机」按钮：局域网地址 + 带口令的二维码。只在本机能拿到。"""
    if not ipaddress.ip_address((req.remote or "127.0.0.1").split("%")[0]).is_loopback and req.cookies.get("tgk") != access_token():
        raise web.HTTPForbidden()
    ip = lan_ip()
    if not ip:
        return web.json_response({"error": "未找到局域网地址；请用 start 脚本启动，或把 TG_FEED_LAN_IP 设为这台电脑的局域网 IP"})
    url = f"http://{ip}:{PORT}/?k={access_token()}"
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=6, border=2, dark="#000", light="#fff")
    return web.json_response({"url": url, "svg": buf.getvalue().decode()})


@web.middleware
async def same_origin(req, handler):
    # 手机/平板：只接受局域网（含 Tailscale 100.64/10）来的请求，且要带访问口令；本机不用口令
    peer = ipaddress.ip_address((req.remote or "127.0.0.1").split("%")[0])
    if not peer.is_loopback:
        # Docker Desktop 的转发地址可能不是私网地址；仍然必须通过下方口令校验。
        if not (peer.is_private or peer in TAILNET or Path("/.dockerenv").exists()):
            raise web.HTTPForbidden()
        token = access_token()
        if req.rel_url.query.get("k") == token:
            # 相机/聊天应用跨应用打开时，Strict Cookie + 302 会在首次跳转丢授权。
            # 直接返回已授权页面，浏览器收下 Cookie 后再由页面清理地址栏。
            resp = await handler(req)
            resp.set_cookie("tgk", token, max_age=365 * 86400, httponly=True, samesite="Lax", path="/")
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["Referrer-Policy"] = "no-referrer"
            return resp
        if req.cookies.get("tgk") != token:
            return web.Response(status=401, text='''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>连接 Telegram-Flow</title>
<style>body{background:#101218;color:#eee;font:16px/1.6 system-ui;padding:28px;max-width:440px;margin:10vh auto}input,button{box-sizing:border-box;font:inherit;padding:12px;border-radius:10px;width:100%;margin:8px 0}button{background:#ff4d6d;color:white;border:0}input{background:#20232b;color:white;border:1px solid #555}</style>
<h2>连接你的 Telegram-Flow</h2><p>请扫描电脑上的完整二维码，或输入「手机」弹窗中显示的访问口令。</p>
<form action="/" method="get"><label for="k">访问口令</label><input id="k" name="k" type="password" required autocomplete="off" autocapitalize="none" spellcheck="false"><button>进入</button></form></html>''', content_type="text/html", headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    origin = req.headers.get("Origin")
    if req.method == "POST" and origin is not None and origin not in (f"http://{req.host}", f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
        raise web.HTTPForbidden()
    if req.path.startswith(("/api/feed", "/api/channels", "/media", "/api/more", "/api/peek", "/api/join", "/api/leave", "/api/pages", "/api/prefetch")) and not TG.ready:
        return web.json_response({"error": "未登录 Telegram，先运行 uv run python login.py"}, status=409)
    try:
        return await handler(req)
    except errors.FloodWaitError as e:
        raise TG.limited(e.seconds) from e


async def on_startup(app):
    await TG.start()
    if TG.ready:
        app["sync"] = asyncio.create_task(TG.loop())


def main() -> None:
    init_storage()
    print("广告筛掉", refresh_filters(), "组")
    app = web.Application(middlewares=[same_origin])
    app.on_startup.append(on_startup)
    app.add_routes([
        web.get("/", index), web.get("/about", about), web.get("/architecture.svg", architecture), web.get("/api/status", status), web.get("/api/channels", channels),
        web.post("/api/channels", select_channels), web.post("/api/more", more), web.get("/api/feed", get_feed),
        web.post("/api/event", event), web.get("/api/taste", taste), web.get("/api/lan", lan),
        web.post("/api/feed", get_feed),
        web.get("/api/peek", peek), web.post("/api/join", join), web.post("/api/leave", leave),
        web.get("/api/pages/{chat}/{msg}", pages), web.get("/media/ext", ext_image),
        web.post("/api/prefetch/{chat}/{msg}", prefetch),
        web.get("/media/image/{chat}/{msg}", image), web.get("/media/video/{chat}/{msg}", video),
    ])
    print(f"Telegram-Flow: http://127.0.0.1:{PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)
