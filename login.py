"""第一次使用：保存 Telegram API 凭据并登录你的账号。

api_id 和 api_hash 在 https://my.telegram.org 的「API development tools」里创建。
登录时 Telegram 会把验证码发到你的 Telegram App；开了两步验证还要输入密码。
"""
import asyncio
import contextlib
import getpass
import json
import os

from telethon import TelegramClient

from telegram_flow.config import CONFIG, DATA, SESSION
from telegram_flow.storage import init_storage


async def main() -> None:
    init_storage()
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text())
    else:
        cfg = {"api_id": int(input("api_id: ").strip()), "api_hash": getpass.getpass("api_hash（输入不回显）: ").strip()}
        CONFIG.write_text(json.dumps(cfg))
        with contextlib.suppress(OSError):  # Windows 挂载目录可能不支持
            os.chmod(CONFIG, 0o600)
    client = TelegramClient(str(SESSION), cfg["api_id"], cfg["api_hash"])
    await client.start()
    me = await client.get_me()
    print(f"已登录：{me.first_name or ''} @{me.username or '-'}")
    await client.disconnect()
    for p in DATA.glob("telegram.session*"):
        with contextlib.suppress(OSError):
            os.chmod(p, 0o600)


if __name__ == "__main__":
    asyncio.run(main())
