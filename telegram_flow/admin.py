"""给部署脚本和 Agent 用的命令行：在容器内通过回环地址调用服务，不需要也不输出访问口令。

    docker compose exec -T tg-feed python -m telegram_flow.admin status
    docker compose exec -T tg-feed python -m telegram_flow.admin channels
    docker compose exec -T tg-feed python -m telegram_flow.admin select <id> [<id> ...]
    docker compose exec -T tg-feed python -m telegram_flow.admin wait [--timeout 900]

只改本机服务的来源选择；不会加入或退出任何 Telegram 频道。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8978"


def call(path: str, body: dict | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def show(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def wait(timeout: float) -> int:
    """等首次同步结束：服务就绪、不在同步、且已有内容。每 15 秒打印一次进度。"""
    deadline = time.monotonic() + timeout
    while True:
        s = call("/api/status")
        print(json.dumps({k: s.get(k) for k in ("ready", "syncing", "channels", "cards", "retry_after")}), flush=True)
        if s.get("ready") and not s.get("syncing") and s.get("cards", 0) > 0:
            return 0
        if time.monotonic() > deadline:
            print("等待超时：同步仍未完成，或选中的来源里没有图片和视频", file=sys.stderr)
            return 1
        time.sleep(15)


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m telegram_flow.admin")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="服务状态")
    sub.add_parser("channels", help="账号已加入的频道和群组，以及是否选中")
    sel = sub.add_parser("select", help="设置选中的来源（整体替换）并开始同步")
    sel.add_argument("ids", nargs="+", type=int)
    w = sub.add_parser("wait", help="等待首次同步完成")
    w.add_argument("--timeout", type=float, default=900)
    a = p.parse_args()
    if a.cmd == "status":
        show(call("/api/status"))
    elif a.cmd == "channels":
        show([{k: c[k] for k in ("id", "title", "kind", "selected")} for c in call("/api/channels")])
    elif a.cmd == "select":
        show(call("/api/channels", {"ids": a.ids}))
    else:
        return wait(a.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
