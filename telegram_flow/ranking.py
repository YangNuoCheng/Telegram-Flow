"""内容编排：读取本地索引，按偏好、新鲜度与热度排序，并分散来源与媒体类型。"""
from __future__ import annotations

import json
import math
import random
import re
import sqlite3
import time

from .features import card_features, flabel
from .filters import FOOTERS, strip_ads
from .learning import SALIENT, model_vec
from .storage import db

# ---------- 排序 ----------

def load_cards(c: sqlite3.Connection, feature: str | None) -> dict[str, list[sqlite3.Row]]:
    rows = c.execute("SELECT i.* FROM item i JOIN channel ch ON ch.id=i.chat_id WHERE ch.selected=1 AND i.blocked=0 "
                     "ORDER BY i.date DESC LIMIT 30000").fetchall()
    cards: dict[str, list] = {}
    for r in rows:
        cards.setdefault(r["gkey"], []).append(r)
    if feature and feature.startswith("q:"):
        terms = feature[2:].lower().split()
        titles = {r[0]: (r[1] or "") for r in c.execute("SELECT id,title FROM channel")}

        def hay(v: list) -> str:
            return " ".join([titles.get(v[0]["chat_id"], "")] + [r["text"] for r in v] + [r["features"] for r in v]).lower()
        cards = {k: v for k, v in cards.items() if all(t in hay(v) for t in terms)}
    elif feature:
        need = feature[2:].split("|") if feature.startswith("x:") else [feature]
        cards = {k: v for k, v in cards.items() if all(f in card_features(v) for f in need)}
    return cards


MIN_GAP = 2       # 同一频道至少隔这么多条再出现
POP_WEIGHT = 0.35  # 点赞/评论多的往前排的力度
WINDOW = 20       # 在最近这么多条里……
MAX_SHARE = 0.25  # ……单个频道最多占这个比例；喜好能把频道往上推，但封顶在这里


def spread_pick(order: list[str], recent: list[str], size: int, explore_rate: float = 0.0,
                media_types: dict[str, str] | None = None, recent_media: list[str] | None = None) -> list[tuple[str, bool]]:
    """按 order 的偏好顺序取 size 条：同频道隔开 MIN_GAP 条，且最近 WINDOW 条里单频道不超过 MAX_SHARE。
    可选的频道不够时自动放宽，所以只看一个频道时照常出。"""
    pool, out, recent = list(order), [], list(recent)
    media_history = list(recent_media or [])
    cap = max(1, round(WINDOW * MAX_SHARE))
    while pool and len(out) < size:
        win = recent[-WINDOW:]
        full = {c for c in set(win) if win.count(c) >= cap}
        near = set(recent[-MIN_GAP:])
        ok = ([k for k in pool if k.split(":")[0] not in near | full]
              or [k for k in pool if k.split(":")[0] not in near] or pool)
        if media_types:
            counts = {t: media_history[-WINDOW:].count(t) for t in ("photo", "video")}
            preferred = min(counts, key=lambda t: (counts[t], t == (media_history[-1] if media_history else "")))
            balanced = [k for k in pool if media_types[k] == preferred]
            if balanced:
                ok = [k for k in ok if media_types[k] == preferred] or ok
        explore = random.random() < explore_rate
        k = random.choice(ok) if explore else ok[0]
        pool.remove(k)
        out.append((k, explore))
        recent.append(k.split(":")[0])
        if media_types:
            media_history.append(media_types[k])
    return out


def feed(mode: str, feature: str | None, exclude: set[str], size: int = 8, recent: list[str] | None = None, recent_media: list[str] | None = None) -> list[dict]:
    recent = recent or []
    with db() as c:
        cards = load_cards(c, feature)
        weights, counts = {}, {}
        for r in c.execute("SELECT feature,w,n FROM weight"):
            weights[r["feature"]], counts[r["feature"]] = r["w"], r["n"]
        names = {f"ch:{r['id']}": r["title"] for r in c.execute("SELECT id,title FROM channel")}
        hidden = {r[0] for r in c.execute("SELECT DISTINCT gkey FROM event WHERE kind='hide'")}
        seen = {r[0] for r in c.execute("SELECT DISTINCT gkey FROM event WHERE kind='impression'")}
        liked = {r[0]: r[1] for r in c.execute("SELECT gkey, MAX(at) FROM event WHERE kind IN ('like','unlike') GROUP BY gkey HAVING SUM(CASE kind WHEN 'like' THEN 1 ELSE -1 END)>0")}
    keys = [k for k in cards if k not in hidden and k not in exclude]
    now = time.time()
    # 热度：点赞 + 2×评论，取对数后和本频道平均比，避免大频道天然压过小频道
    pop = {k: math.log1p(max(r["reactions"] for r in v) + 2 * max(r["replies"] for r in v)) for k, v in cards.items()}
    by_ch: dict[str, list[float]] = {}
    for k, p in pop.items():
        by_ch.setdefault(k.split(":")[0], []).append(p)
    ch_mean = {ch: sum(v) / len(v) for ch, v in by_ch.items()}

    def score(k: str) -> tuple[float, list[str]]:
        feats = card_features(cards[k])
        vec = model_vec(feats)
        contrib = sorted(((weights.get(f, 0.0) * x, f) for f, x in vec if f != "bias"), reverse=True)
        s = sum(v for v, _ in contrib)
        # 没怎么见过的关键词给一点试探分，避免越推越窄
        novel = [1 / math.sqrt(1 + counts.get(f, 0)) for f in feats if f.startswith(SALIENT)]
        s += 0.2 * (sum(novel) / len(novel) if novel else 0)
        age_days = (now - max(r["date"] for r in cards[k])) / 86400
        s += 0.3 * math.exp(-age_days / 30)
        s += POP_WEIGHT * (0.7 * (pop[k] - ch_mean[k.split(":")[0]]) + 0.3 * pop[k] / 4)
        if k in seen:  # 钻进某个频道或标签时，看过的也给，但排在没看过的后面
            s -= 1.0
        why = [flabel(f, names) for v, f in contrib if v > 0.03 and not f.startswith(("kind:", "dur:"))][:3]
        return s, why

    media_types = {k: "video" if any(r["kind"] != "photo" for r in rows) else "photo" for k, rows in cards.items()}
    if mode == "liked":
        keys = sorted((k for k in keys if k in liked), key=lambda k: -liked[k])[:size]
        return [card(k, cards[k], []) for k in keys]
    if mode == "new":
        order = sorted((k for k in keys if k not in seen), key=lambda k: -max(r["date"] for r in cards[k]))[:size * 40]
        return [card(k, cards[k], []) for k, _ in spread_pick(order, recent, size, media_types=media_types, recent_media=recent_media)]
    fresh = keys if feature else [k for k in keys if k not in seen]
    scored = sorted(((score(k), k) for k in fresh), key=lambda x: -x[0][0])
    reasons = {k: why for (s, why), k in scored}
    return [card(k, cards[k], [] if ex else reasons[k], ex)
            for k, ex in spread_pick([k for _, k in scored], recent, size, explore_rate=0.15, media_types=media_types, recent_media=recent_media)]


def card(key: str, rows: list[sqlite3.Row], why: list[str], explore: bool = False) -> dict:
    rows = sorted(rows, key=lambda r: r["msg_id"])
    text_rows = rows
    if any(r["kind"] != "photo" for r in rows):  # 同组里有视频：只放视频，封面图不要
        rows = [r for r in rows if r["kind"] != "photo"]
    with db() as c:
        ch = c.execute("SELECT title, username FROM channel WHERE id=?", (rows[0]["chat_id"],)).fetchone()
    text = next((r["text"] for r in text_rows if r["text"]), "")
    first = text_rows[0]
    link = f"https://t.me/{ch['username']}/{first['msg_id']}" if ch and ch["username"] else None
    title = ch["title"] if ch else ""
    # 漫画：正文提到评论区 / 汉化 / 作品 / 同人志；只是「#xx图 #漫画 #壁纸」这种单图合集不算
    comic = all(r["kind"] == "photo" for r in rows) and bool(
        re.search(r"评论区|汉化|同人志|作品[:：]|全彩|comic|manga|doujin", text, re.I)
        or ("漫画" in text and not re.search(r"#\S*图|壁纸|背景", text)))
    foot = FOOTERS.get(first["chat_id"], ())
    text = "\n".join(l for l in text.splitlines() if l.strip() not in foot)
    return {
        "key": key, "channel": {"id": first["chat_id"], "title": title}, "text": strip_ads(text), "comic": comic,
        "reactions": max(r["reactions"] for r in text_rows), "replies": max(r["replies"] for r in text_rows),
        "date": first["date"], "link": link, "why": why, "explore": explore,
        "media": [{"chat": r["chat_id"], "msg": r["msg_id"], "kind": r["kind"], "duration": r["duration"],
                   "width": r["width"], "height": r["height"]} for r in rows],
        "tags": [f for f in json.loads(first["features"]) if f.startswith(("tag:", "at:"))][:8],
    }
