"""在线媒体转发：图片、视频分块与阅读页图片按需读取，只缓存在内存。"""
from __future__ import annotations

import asyncio
import re
from collections import OrderedDict

import aiohttp
from aiohttp import web
from telethon import errors, types, utils

from .config import CHUNK, DATA
from .telegram import INVITE, TG, describe


async def image(req):
    chat, msg = int(req.match_info["chat"]), int(req.match_info["msg"])
    thumb = req.rel_url.query.get("thumb") == "1"
    key = (chat, msg, thumb)
    data = MEM_IMAGES.get(key)
    if data is None:
        if key not in IMG_INFLIGHT:  # 预载和显示同时要同一张图时只下载一次
            IMG_INFLIGHT[key] = asyncio.ensure_future(fetch_image(chat, msg, thumb))
        try:
            data = await asyncio.shield(IMG_INFLIGHT[key])
        finally:
            if IMG_INFLIGHT.get(key) is not None and IMG_INFLIGHT[key].done():
                IMG_INFLIGHT.pop(key, None)
        if not data:
            raise web.HTTPNotFound()
    MEM_IMAGES.move_to_end(key)
    return web.Response(body=data, content_type="image/jpeg", headers={"Cache-Control": "no-store"})


IMG_INFLIGHT: dict[tuple, asyncio.Future] = {}


async def fetch_image(chat: int, msg: int, thumb: bool) -> bytes:
    global MEM_BYTES
    m = await TG.message(chat, msg)
    data = await TG.client.download_media(m, file=bytes, thumb=-1 if (thumb or not m.photo) else None)
    if data:
        MEM_IMAGES[(chat, msg, thumb)] = data
        MEM_BYTES += len(data)
        while MEM_BYTES > MEM_LIMIT and MEM_IMAGES:
            MEM_BYTES -= len(MEM_IMAGES.popitem(last=False)[1])
    return data or b""


# 图片只缓存在内存里，进程退出即消失，不写硬盘
MEM_IMAGES: OrderedDict[tuple, bytes] = OrderedDict()
MEM_BYTES = 0
MEM_LIMIT = 200 * 1024 * 1024



PAGES: OrderedDict[tuple[int, int], dict] = OrderedDict()

# 能看全本的链接：telegra.ph 阅读页、频道里的帖子链接、常见创作平台和网盘；邀请链接、bot、广告域名不算。
# 其他阅读站点写在 data/read_domains.txt：一行一个不带后缀的站点名（example 匹配 example.com、www.example.org 等）。
READ_SITES = [r"pixiv", r"fanbox", r"mega", r"pan\.baidu", r"quark", r"aliyundrive", r"alipan", r"123pan", r"lanzou\w*",
              r"drive\.google"]


def read_sites() -> list[str]:
    path = DATA / "read_domains.txt"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return READ_SITES + [re.escape(s.strip().lower()) for s in lines if s.strip() and not s.lstrip().startswith("#")]


READ_LINK = re.compile(r"https?://(?:telegra\.ph|graph\.org|te\.legra\.ph)/[^\s)）\]]+|"
                       r"https?://t\.me/(?!\+|joinchat)(?:c/)?[A-Za-z0-9_]+/\d+|"
                       r"https?://(?:[\w-]+\.)*(?:" + "|".join(read_sites()) + r")\.\w+[^\s)）\]]*", re.I)
TELEGRAPH = re.compile(r"https?://(?:telegra\.ph|graph\.org|te\.legra\.ph)/([^\s/?#)）\]]+)", re.I)
READ_WORD = re.compile(r"阅读|观看|打开|全本|在线|看漫|read|view", re.I)
IMG_SRC = re.compile(r"""<img[^>]+?(?:data-src|src)=["']([^"']+)["']""", re.I)
EXT_OK: set[str] = set()   # 只代理从阅读页里取出来的图片地址
_HTTP: dict = {}


def http() -> aiohttp.ClientSession:
    s = _HTTP.get("s")
    if s is None or s.closed:
        s = _HTTP["s"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15),
                                               headers={"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 Safari/605.1.15"})
    return s


def msg_links(m) -> list[str]:
    """帖子正文、隐藏在文字里的链接（「点击阅读：打开漫画」）、链接按钮。
    白名单站点直接算；其他链接要锚文字像「阅读 / 打开 / 观看 / 全本」才算，广告链接就进不来。"""
    found = list(READ_LINK.findall(m.message or ""))
    try:
        ents = m.get_entities_text()
    except Exception:
        ents = []
    for e, t in ents:
        url = getattr(e, "url", None) or (t if isinstance(e, types.MessageEntityUrl) else None)
        if not url:
            continue
        url = url if url.startswith("http") else "https://" + url
        if READ_LINK.match(url) or (READ_WORD.search(t) and not INVITE.search(url)):
            found.append(url)
    for row in getattr(getattr(m, "reply_markup", None), "rows", None) or []:
        for b in row.buttons:
            url = getattr(b, "url", None)
            if url and (READ_LINK.match(url) or READ_WORD.search(b.text or "")) and not INVITE.search(url):
                found.append(url)
    return found


async def telegraph_pages(url: str) -> list[dict]:
    """阅读页（telegra.ph 或仿 telegra.ph 的网页）：取出里面的图片当作页。
    图片经本机服务转发、只放内存，浏览器不直接连外站。"""
    m = TELEGRAPH.search(url)
    srcs: list[str] = []
    try:
        if m:
            async with http().get(f"https://api.telegra.ph/getPage/{m.group(1)}", params={"return_content": "true"}) as r:
                data = await r.json()

            def walk(nodes):
                for n in nodes or []:
                    if isinstance(n, dict):
                        src = (n.get("attrs") or {}).get("src")
                        if n.get("tag") == "img" and src:
                            srcs.append(src if src.startswith("http") else "https://telegra.ph" + src)
                        walk(n.get("children"))
            walk((data.get("result") or {}).get("content"))
        else:
            async with http().get(url) as r:
                if "html" not in r.headers.get("Content-Type", "") or (r.content_length or 0) > 5_000_000:
                    return []
                html = (await r.content.read(5_000_000)).decode("utf-8", "ignore")
            base = str(r.url)
            from urllib.parse import urljoin
            srcs = [urljoin(base, s) for s in IMG_SRC.findall(html)]
            srcs = [s for s in srcs if re.search(r"\.(?:jpe?g|png|webp|gif|avif)(?:\?|$)", s, re.I)]
    except Exception:
        return []
    srcs = list(dict.fromkeys(srcs))
    EXT_OK.update(srcs)
    from urllib.parse import quote
    return [{"kind": "photo", "url": "/media/ext?u=" + quote(s, safe="")} for s in srcs]


async def ext_image(req):
    """转发阅读页里的图片：只放内存，不写硬盘。"""
    url = req.rel_url.query.get("u", "")
    if url not in EXT_OK:
        raise web.HTTPForbidden()
    key = ("ext", url)
    data = MEM_IMAGES.get(key)
    if data is None:
        try:
            async with http().get(url) as r:
                if r.status != 200:
                    raise web.HTTPNotFound()
                data = await r.read()
        except aiohttp.ClientError:
            raise web.HTTPBadGateway()
        global MEM_BYTES
        MEM_IMAGES[key] = data
        MEM_BYTES += len(data)
        while MEM_BYTES > MEM_LIMIT and MEM_IMAGES:
            MEM_BYTES -= len(MEM_IMAGES.popitem(last=False)[1])
    MEM_IMAGES.move_to_end(key)
    kind = "image/webp" if url.split("?")[0].endswith(".webp") else "image/png" if url.split("?")[0].endswith(".png") else "image/jpeg"
    return web.Response(body=data, content_type=kind, headers={"Cache-Control": "no-store"})


async def pages(req):
    """漫画类帖子：评论区的图片当作页；再找能看全本的链接（正文、按钮、评论、紧跟着的几条帖子）。
    telegra.ph 的链接直接展开成页。都找不到的话前端就不推这条。只在内存里记。"""
    chat, msg = int(req.match_info["chat"]), int(req.match_info["msg"])
    key = (chat, msg)
    if key not in PAGES:
        out, links = [], []
        post = await TG.message(chat, msg)
        links += msg_links(post)
        has_comments = bool(getattr(getattr(post, "replies", None), "replies", 0))
        try:
            async for m in (TG.client.iter_messages(chat, reply_to=msg, reverse=True, limit=400) if has_comments else _none()):
                links += msg_links(m)
                d = describe(m)
                d = describe(m)
                if d is None:
                    if m.document and (m.document.mime_type or "").startswith("image/"):
                        d = {"kind": "photo", "duration": None, "width": None, "height": None}
                    else:
                        continue
                if d["kind"] != "photo" and d["duration"] is not None and d["duration"] < 3:  # 表情动图之类
                    continue
                cid = utils.get_peer_id(m.peer_id)
                TG.cache_message(cid, m)
                out.append({"chat": cid, "msg": m.id, "kind": d["kind"], "duration": d["duration"],
                            "width": d["width"], "height": d["height"]})
        except errors.MsgIdInvalidError:
            out = []
        try:  # 紧跟着的几条纯文字帖子（半小时内）常常是「全本链接」；带图的是下一本，不算
            nearby = [] if links or len(out) >= 3 else await TG.fetch_messages(chat, list(range(msg + 1, msg + 7)))
            for m in nearby:
                if m is not None and (m.media is None or isinstance(m.media, types.MessageMediaWebPage)):
                    if abs((m.date - post.date).total_seconds()) < 1800:
                        links += msg_links(m)
        except web.HTTPTooManyRequests:
            raise
        except Exception:
            pass
        links = list(dict.fromkeys(links))
        if sum(p["kind"] == "photo" for p in out) < 3:
            for u in links:
                tp = await telegraph_pages(u)
                if len(tp) >= 3:
                    out += tp
                    break
        while len(TG.messages) > 6000:
            TG.messages.popitem(last=False)
        PAGES[key] = {"pages": out, "links": links[:5]}
        while len(PAGES) > 200:
            PAGES.popitem(last=False)
    PAGES.move_to_end(key)
    return web.json_response(PAGES[key])


async def _none():
    return
    yield


async def video(req):
    chat, msg = int(req.match_info["chat"]), int(req.match_info["msg"])
    m = await TG.message(chat, msg)
    doc = m.document
    size = doc.size
    start, end = 0, size - 1
    rng = re.match(r"bytes=(\d*)-(\d*)", req.headers.get("Range", ""))
    if rng:
        if rng.group(1):
            start = int(rng.group(1))
            end = int(rng.group(2)) if rng.group(2) else size - 1
        else:
            start = max(size - int(rng.group(2)), 0)
    end = min(end, size - 1)
    if start > end:
        raise web.HTTPRequestRangeNotSatisfiable(headers={"Content-Range": f"bytes */{size}"})
    resp = web.StreamResponse(status=206 if rng else 200, headers={
        "Content-Type": doc.mime_type or "video/mp4", "Accept-Ranges": "bytes", "Cache-Control": "no-store",
        "Content-Length": str(end - start + 1), "Content-Range": f"bytes {start}-{end}/{size}"})
    await resp.prepare(req)
    first, last = start // CHUNK, end // CHUNK
    try:
        async for idx, chunk in chunk_range(doc, first, last):
            lo = start - idx * CHUNK if idx == first else 0
            hi = end - idx * CHUNK + 1 if idx == last else len(chunk)
            await resp.write(chunk[lo:hi])
    except (ConnectionResetError, ConnectionError, asyncio.CancelledError):
        pass
    return resp


# ---------- 视频分块：内存缓存 + 并行拉取 + 预载 ----------
# 只在内存里，进程退出即消失，不写硬盘
CHUNKS: OrderedDict[tuple[int, int], bytes] = OrderedDict()
CHUNK_BYTES = 0
CHUNK_LIMIT = 600 * 1024 * 1024
INFLIGHT: dict[tuple[int, int], asyncio.Future] = {}
PARALLEL = 6
PREFETCH_SEM = asyncio.Semaphore(3)  # 预载最多同时 3 个请求，给正在播的让路
VIDEO_SEM = asyncio.Semaphore(10)    # 视频分块总并发上限，图片不受限，保证翻到图片时马上出来


async def get_chunk(doc, idx: int, sem: asyncio.Semaphore | None = None) -> bytes:
    global CHUNK_BYTES
    key = (doc.id, idx)
    if key in CHUNKS:
        CHUNKS.move_to_end(key)
        return CHUNKS[key]
    if key in INFLIGHT:
        return await asyncio.shield(INFLIGHT[key])
    fut = asyncio.get_running_loop().create_future()
    INFLIGHT[key] = fut
    try:
        if sem:
            await sem.acquire()
        try:
            data = b""
            async with VIDEO_SEM:
                async for c in TG.client.iter_download(doc, offset=idx * CHUNK, request_size=CHUNK, limit=1, file_size=doc.size):
                    data = bytes(c)
        finally:
            if sem:
                sem.release()
        CHUNKS[key] = data
        CHUNK_BYTES += len(data)
        while CHUNK_BYTES > CHUNK_LIMIT and CHUNKS:
            CHUNK_BYTES -= len(CHUNKS.popitem(last=False)[1])
        fut.set_result(data)
        return data
    except BaseException as e:
        if not fut.done():
            fut.set_exception(e)
            fut.exception()  # 标记已读，避免无人等待时报警
        raise
    finally:
        INFLIGHT.pop(key, None)


async def chunk_range(doc, first: int, last: int):
    """按顺序产出 [first, last] 的块，同时并行预取后面的 PARALLEL 块。"""
    tasks: dict[int, asyncio.Task] = {}
    nxt = first
    try:
        for idx in range(first, last + 1):
            while nxt <= last and nxt < idx + PARALLEL:
                tasks[nxt] = asyncio.ensure_future(get_chunk(doc, nxt))
                nxt += 1
            yield idx, await tasks.pop(idx)
    finally:
        for t in tasks.values():
            t.cancel()


def find_moov(head: bytes, size: int) -> tuple[int, int] | None:
    """从文件开头解析顶层 box，找到 moov 的字节范围（moov 在文件末尾时浏览器必须先拉它）。"""
    off = 0
    while off + 8 <= size:
        if off + 16 > len(head):
            return None
        n = int.from_bytes(head[off:off + 4], "big")
        kind = head[off + 4:off + 8]
        if n == 1:
            n = int.from_bytes(head[off + 8:off + 16], "big")
        elif n == 0:
            n = size - off
        if kind == b"moov":
            return off, min(size, off + n) - 1
        if n < 8:
            return None
        off += n
        if off >= len(head) and off < size:  # 下一个 box 在头部之外：大概率就是末尾的 moov
            return off, size - 1
    return None


async def warm_video(doc, at: float) -> None:
    size = doc.size
    last = (size - 1) // CHUNK
    head = await get_chunk(doc, 0, PREFETCH_SEM)
    want = [1]
    mv = find_moov(head, size)
    if mv and mv[0] >= CHUNK:
        want += list(range(mv[0] // CHUNK, mv[1] // CHUNK + 1))
    if at > 0:
        mid = int(size * at) // CHUNK
        want += list(range(max(0, mid - 1), mid + 4))
    want = [i for i in dict.fromkeys(want) if 0 <= i <= last][:60]
    await asyncio.gather(*(get_chunk(doc, i, PREFETCH_SEM) for i in want), return_exceptions=True)


WARMING: set[int] = set()


async def prefetch(req):
    chat, msg = int(req.match_info["chat"]), int(req.match_info["msg"])
    at = float(req.rel_url.query.get("at", "0") or 0)
    m = await TG.message(chat, msg)
    doc = m.document
    if doc is None or doc.id in WARMING:
        return web.json_response({"ok": True})
    WARMING.add(doc.id)

    async def run():
        try:
            await warm_video(doc, at)
        except Exception as e:
            print(f"预载失败 {chat}/{msg}: {e}")
        finally:
            WARMING.discard(doc.id)
    asyncio.create_task(run())
    return web.json_response({"ok": True})
