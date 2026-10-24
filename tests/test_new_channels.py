"""New channels joined in Telegram are auto-selected after the first import; no real Telegram or user data."""
import sqlite3
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from telegram_flow import telegram as tg


def dialog(peer_id, name, channel=True):
    ent = SimpleNamespace(id=peer_id, username=None)
    return SimpleNamespace(is_channel=True, is_group=not channel, name=name, entity=ent, peer=peer_id)


class FakeClient:
    def __init__(self, items):
        self.items = items

    async def iter_dialogs(self):
        for d in self.items:
            yield d


class NewChannelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE channel(id INTEGER PRIMARY KEY, title TEXT NOT NULL, username TEXT, "
                          "kind TEXT NOT NULL, selected INTEGER NOT NULL DEFAULT 0)")

        @contextmanager
        def fake_db():
            yield self.conn
            self.conn.commit()

        self.patches = [patch.object(tg, "db", fake_db), patch.object(tg.utils, "get_peer_id", lambda e: e.id),
                        patch.object(tg, "blocklist", lambda: ["blockedword"])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def selected(self):
        return {r["id"]: r["selected"] for r in self.conn.execute("SELECT id, selected FROM channel")}

    async def test_only_channels_joined_after_first_import_are_selected(self):
        t = tg.Telegram()
        t.client = FakeClient([dialog(1, "a"), dialog(2, "b")])
        await t.dialogs()
        self.assertEqual(self.selected(), {1: 0, 2: 0})
        self.conn.execute("UPDATE channel SET selected=1 WHERE id=1")
        self.conn.execute("UPDATE channel SET selected=0 WHERE id=2")
        t.client = FakeClient([dialog(1, "a"), dialog(2, "b"), dialog(3, "c"), dialog(4, "g", channel=False),
                               dialog(5, "x BlockedWord x")])
        out = await t.dialogs()
        self.assertEqual(self.selected(), {1: 1, 2: 0, 3: 1, 4: 0, 5: 0})
        self.assertEqual([d["id"] for d in out if d["new"]], [3])


if __name__ == "__main__":
    unittest.main()
