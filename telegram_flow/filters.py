"""内容过滤：屏蔽词、推广段落识别、频道固定尾巴清理。"""
from __future__ import annotations

import re

from .storage import blocklist, db

# ---------- 广告筛选 ----------
# 先去掉频道每帖都挂的固定尾巴（「群主推荐VPN / 广告合作」），再按剩下的文案打分：
# 博彩、付费广告、XX.COM、SOSO 导流、VPN、兼职、AI 聊天 app 等是强信号，「官方 / 加入 / 客服」是弱信号，满屏 emoji 加分。
AD_STRONG = re.compile(r"付费广告|出款|首存|首充|彩金|返水|返佣|usdt|注册送|新人注册|博彩|娱乐城|体育投注|真人视讯|电子可拉|一注|上押|担保|代理双享|"
                       r"净盈利|分红|soso|搜搜|日结|dzmm|vpn|机场订阅|机场节点|高性价比机场|加速器|翻墙|钱包|网赚|招商|包网|盘口|彩票|百家乐|捕鱼|棋牌|包出款|充提|盘总|见面付款|注册秒送", re.I)
AD_WEAK = re.compile(r"官方|加入|代理|客服|充值|福利群|会员群|豪礼|领取|限时免费|私聊|联系|商务|合作|推广|兼职|@\w+bot\b", re.I)
AD_DOMAIN = re.compile(r"\b[A-Z0-9]{1,10}\.(?:COM|NET|CC|VIP|TOP)\b")
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def ad_score(text: str) -> int:
    s = 3 * len(set(m.casefold() for m in AD_STRONG.findall(text)))
    s += 3 * bool(AD_DOMAIN.search(text))
    s += len(set(AD_WEAK.findall(text)))
    s += 2 * (len(EMOJI.findall(text)) >= 12)
    return s


PARA_SPLIT = re.compile(r"\n\s*\n|\n?(?:=\s*){5,}\n?")


def is_ad(body: str) -> bool:
    """检查完整文案，不能因为首段像标题就豁免后续促销。"""
    return ad_score(body) >= 3


def strip_ads(text: str) -> str:
    """显示时去掉帖子里的广告段落。"""
    paras = PARA_SPLIT.split(text)
    keep = [p.strip() for p in paras if p.strip() and ad_score(p) < 3]
    return "\n\n".join(keep)


FOOTERS: dict[int, set[str]] = {}  # 各频道每帖都挂的固定尾巴，显示时去掉


def refresh_filters() -> int:
    """重算每组帖子的屏蔽状态：1=命中屏蔽词，2=广告，0=正常。屏蔽词表改了或新同步进来都会生效。"""
    block = blocklist()
    with db() as c:
        groups: dict[str, list] = {}
        for r in c.execute("SELECT chat_id, gkey, text FROM item"):
            groups.setdefault(r["gkey"], [r["chat_id"], []])[1].append(r["text"] or "")
        lines_df: dict[int, dict[str, int]] = {}
        posts: dict[int, int] = {}
        for chat, texts in groups.values():
            posts[chat] = posts.get(chat, 0) + 1
            for ln in {l.strip() for t in texts for l in t.splitlines() if len(l.strip()) >= 4}:
                lines_df.setdefault(chat, {})[ln] = lines_df.setdefault(chat, {}).get(ln, 0) + 1
        footer = {ch: {l for l, n in df.items() if posts[ch] >= 20 and n >= 0.25 * posts[ch]} for ch, df in lines_df.items()}
        FOOTERS.clear()
        FOOTERS.update(footer)
        out, ads = [], 0
        for gkey, (chat, texts) in groups.items():
            full = "\n".join(dict.fromkeys(texts))
            if any(b in full.casefold() for b in block):
                flag = 1
            else:
                # 广告也会跨帖重复，重复文案只能在展示时清理，不能在广告识别前删除。
                flag = 2 if is_ad(full) else 0
                ads += flag == 2
            out.append((flag, gkey))
        c.executemany("UPDATE item SET blocked=? WHERE gkey=?", out)
    return ads
