"""本地偏好学习：特征向量、投入度信号、在线权重更新与重训练。"""
from __future__ import annotations

import math
import sqlite3

from .features import card_features

# ---------- 偏好学习 ----------
# 每个帖子由一组特征表示（频道、话题标签、@提及、标题里的词、媒体类型、时长档），
# 再加上部分特征两两组合（如「摄影标签+长视频」），学习特定组合的偏好。
# 每看一条算一个投入度 y∈[-1,1]：停留和你自己的中位停留比（图片、视频分开），秒划为负，
# 点赞/隐藏/开声音/拖进度条各有对应值。模型预测 ŷ=Σw·x，按误差 y-ŷ 修正权重并带一点衰减，
# 所以人人都有的特征（比如「视频」）不会无限涨，真正区分口味的组合会浮上来。

MODEL_VERSION = "5"
LR, L2 = 0.3, 0.003
ACTION_Y = {"like": 1.0, "unlike": -0.6, "hide": -1.0, "open": 0.5, "unmute": 0.5, "skip": -0.5}
SALIENT = ("tag:", "w:", "at:")


def model_vec(feats: list[str]) -> list[tuple[str, float]]:
    singles = [f for f in feats]
    core = [f for f in feats if f.startswith(SALIENT)][:6] + [f for f in feats if f.startswith(("ch:", "kind:", "dur:"))]
    # 只在「类型/时长」之间互配的组合（图片+视频、<1m+<5m）是一组帖子的形态，不是口味
    form = ("kind:", "dur:")
    pairs = [f"x:{a}|{b}" for i, a in enumerate(core) for b in core[i + 1:]
             if not (a.startswith(form) and b.startswith(form))]
    out = [("bias", 1.0)]
    out += [(f, 1 / math.sqrt(len(singles))) for f in singles] if singles else []
    out += [(p, 0.7 / math.sqrt(len(pairs))) for p in pairs] if pairs else []
    return out


def engagement(kind: str, ms: float, is_video: bool, typical: float) -> float | None:
    if kind != "dwell":
        return ACTION_Y.get(kind)
    secs = ms / 1000
    if secs < 1.2:
        return -0.7
    y = math.tanh(math.log(secs / typical))
    if is_video and secs > 90:
        y = min(1.0, y + 0.3)
    return y


def median_dwell(values: list[float], is_video: bool) -> float:
    if len(values) < 5:
        return 10.0 if is_video else 4.0
    v = sorted(values[-200:])
    return min(60.0, max(2.0, v[len(v) // 2]))


def update(c: sqlite3.Connection, feats: list[str], y: float, cache: dict | None = None) -> None:
    vec = model_vec(feats)
    if cache is None:
        names = [f for f, _ in vec]
        got = {}
        for i in range(0, len(names), 400):
            part = names[i:i + 400]
            got.update({r[0]: r[1] for r in c.execute(f"SELECT feature,w FROM weight WHERE feature IN ({','.join('?' * len(part))})", part)})
        w = got
    else:
        w = cache
    err = y - sum(w.get(f, 0.0) * x for f, x in vec)
    for f, x in vec:
        nw = w.get(f, 0.0) + LR * (err * x - L2 * w.get(f, 0.0))
        w[f] = nw
        if cache is None:
            c.execute("INSERT INTO weight(feature,w,n) VALUES(?,?,1) ON CONFLICT(feature) DO UPDATE SET w=excluded.w, n=n+1", (f, nw))


def retrain(c: sqlite3.Connection) -> None:
    """按新规则用全部历史事件重算权重。"""
    w: dict[str, float] = {}
    n: dict[str, int] = {}
    dwell = {True: [], False: []}
    items: dict[str, list] = {}
    for e in c.execute("SELECT gkey,kind,value FROM event WHERE kind!='impression' ORDER BY id").fetchall():
        rows = items.get(e["gkey"])
        if rows is None:
            rows = items[e["gkey"]] = c.execute("SELECT * FROM item WHERE gkey=?", (e["gkey"],)).fetchall()
        if not rows:
            continue
        is_video = any(r["kind"] != "photo" for r in rows)
        y = engagement(e["kind"], e["value"] or 0, is_video, median_dwell(dwell[is_video], is_video))
        if e["kind"] == "dwell":
            dwell[is_video].append((e["value"] or 0) / 1000)
        if y is None:
            continue
        feats = card_features(rows)
        update(c, feats, y, w)
        for f, _ in model_vec(feats):
            n[f] = n.get(f, 0) + 1
    c.execute("DELETE FROM weight")
    c.executemany("INSERT INTO weight(feature,w,n) VALUES(?,?,?)", [(f, v, n.get(f, 1)) for f, v in w.items()])
    c.execute("INSERT INTO meta(k,v) VALUES('model',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (MODEL_VERSION,))
