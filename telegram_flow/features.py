"""从帖子文本中提取特征：话题标签、提及、关键词、频道模板词。"""
from __future__ import annotations

import json
import re
import sqlite3
import time

from .config import DB

CJK_RUN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]{2,8}")
LATIN = re.compile(r"[a-z][a-z0-9_\-]{1,24}")
HASHTAG = re.compile(r"#([\w\u3040-\u30ff\u3400-\u9fff]+)")
MENTION = re.compile(r"@([A-Za-z0-9_]{4,32})")
STOP = {"http", "https", "www", "com", "the", "and", "for", "with", "this", "that", "join", "channel"}




def tokens(text: str) -> list[str]:
    low = text.casefold()
    out = [f"tag:{t}" for t in HASHTAG.findall(low)]
    out += [f"at:{m}" for m in MENTION.findall(low)]
    plain = MENTION.sub(" ", HASHTAG.sub(" ", re.sub(r"https?://\S+", " ", low)))
    out += [f"w:{w}" for w in LATIN.findall(plain) if w not in STOP]
    out += [f"w:{w}" for w in CJK_RUN.findall(plain)]
    seen, result = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result[:24]



def flabel(f: str, names: dict) -> str:
    if f.startswith("x:"):
        return "+".join(flabel(p, names) for p in f[2:].split("|"))
    kind, _, v = f.partition(":")
    return {"tag": "#" + v, "at": "@" + v, "ch": names.get(f, "频道"), "w": v,
            "kind": {"video": "视频", "photo": "图片", "gif": "动图"}.get(v, v), "dur": "时长" + v}.get(kind, f)


def card_features(rows: list[sqlite3.Row]) -> list[str]:
    chat = rows[0]["chat_id"]
    feats = {f"ch:{chat}"}
    boiler = boilerplate().get(chat, ())
    for r in rows:
        for f in json.loads(r["features"]):
            if f in boiler:
                continue
            if f.startswith("w:"):
                f = clean_word(f[2:])
                if not f:
                    continue
            feats.add(f)
    return sorted(feats)


# 广告/引流话术（「点击搜索更多资源」「xx频道」）和虚词边缘不算口味；
# 中文连续串只保留 2–6 字，更长的多半是整句标题，复现率低只会添噪声。
AD_WORD = re.compile(r"点击|搜索|资源|频道|关注|订阅|加入|投稿|更多|群组|链接|下载|免费|福利|广告|客服|会员|回复|评论区|查看")
EDGE = "的了是在被和与把让就也都还又很"


def clean_word(w: str) -> str:
    if CJK_RUN.fullmatch(w):
        w = w.strip(EDGE)
        if not 2 <= len(w) <= 6 or AD_WORD.search(w):
            return ""
    return "w:" + w


_BOILER: dict = {"at": 0.0, "data": {}}


def boilerplate() -> dict[int, set[str]]:
    """频道模板词：一个频道里超过 30% 的帖子都带的词（「评论区查看全部内容」之类），不算口味。"""
    if time.time() - _BOILER["at"] < 600:
        return _BOILER["data"]
    out: dict[int, set[str]] = {}
    con = sqlite3.connect(DB)
    try:
        posts: dict[int, dict[str, set]] = {}
        for chat, gkey, feats in con.execute("SELECT chat_id, gkey, features FROM item"):
            posts.setdefault(chat, {}).setdefault(gkey, set()).update(json.loads(feats))
        for chat, groups in posts.items():
            if len(groups) < 20:
                continue
            df: dict[str, int] = {}
            for fs in groups.values():
                for f in fs:
                    if f.startswith(("w:", "tag:", "at:")):
                        df[f] = df.get(f, 0) + 1
            out[chat] = {f for f, n in df.items() if n > 0.3 * len(groups)}
    finally:
        con.close()
    _BOILER.update(at=time.time(), data=out)
    return out
