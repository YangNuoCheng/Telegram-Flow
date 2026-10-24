"""Regression checks for local queue requests; no Telegram or database access."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from telethon import errors

from telegram_flow import ranking, server
from telegram_flow.telegram import Telegram


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_simultaneous_media_requests_share_one_lookup(self):
        telegram = Telegram()
        message = SimpleNamespace(id=7, media=True)
        telegram.client = SimpleNamespace(get_messages=AsyncMock(return_value=message))
        messages = await asyncio.gather(*(telegram.message(10, 7) for _ in range(12)))
        self.assertTrue(all(m is message for m in messages))
        telegram.client.get_messages.assert_awaited_once()

    async def test_flood_wait_stops_new_lookups_but_keeps_cached_media(self):
        telegram = Telegram()
        error = errors.FloodWaitError(request=None, capture=29)
        telegram.client = SimpleNamespace(get_messages=AsyncMock(side_effect=error))
        with self.assertRaises(web.HTTPTooManyRequests) as caught:
            await telegram.message(10, 7)
        self.assertGreaterEqual(int(caught.exception.headers['Retry-After']), 28)
        deadline = telegram.retry_until
        with self.assertRaises(web.HTTPTooManyRequests):
            await telegram.message(20, 8)
        self.assertEqual(telegram.retry_until, deadline)
        telegram.client.get_messages.assert_awaited_once()
        cached = SimpleNamespace(id=9, media=True)
        telegram.cache_message(10, cached)
        self.assertIs(await telegram.message(10, 9), cached)
        telegram.retry_until = 0
        telegram.client.get_messages.side_effect = None
        telegram.client.get_messages.return_value = cached
        self.assertIs(await telegram.message(20, 9), cached)

    async def test_feed_keeps_large_exclusion_list_without_telegram_lookup(self):
        telegram = Telegram()
        telegram.client = SimpleNamespace(get_messages=AsyncMock())
        request = make_mocked_request('POST', '/api/feed')
        request.json = AsyncMock(return_value={
            'mode': 'new', 'exclude': ['item:' + str(i) for i in range(600)],
        })
        with patch.object(server, 'TG', telegram), patch.object(server, 'feed', return_value=[]) as feed:
            response = await server.get_feed(request)
        self.assertEqual(json.loads(response.text), [])
        self.assertEqual(len(feed.call_args.args[2]), 600)
        telegram.client.get_messages.assert_not_awaited()

    async def test_startup_buffer_accepts_200_without_telegram_lookup(self):
        request = make_mocked_request('POST', '/api/feed')
        request.json = AsyncMock(return_value={'size': 200, 'recentMedia': ['video']})
        with patch.object(server, 'feed', return_value=[]) as feed:
            await server.get_feed(request)
        self.assertEqual(feed.call_args.kwargs['size'], 200)
        self.assertEqual(feed.call_args.kwargs['recent_media'], ['video'])

    async def test_balanced_types_across_batches_preserve_channel_spacing(self):
        order = [f'{i % 10}:v{i}' for i in range(120)] + [f'{i % 10}:p{i}' for i in range(120)]
        types = {k: 'video' if ':v' in k else 'photo' for k in order}
        first = [k for k, _ in ranking.spread_pick(order, [], 101, media_types=types)]
        second = [k for k, _ in ranking.spread_pick([k for k in order if k not in first],
                  [k.split(':')[0] for k in first[-20:]], 99, media_types=types,
                  recent_media=[types[k] for k in first[-20:]])]
        result = first + second
        self.assertEqual(sum(types[k] == 'video' for k in result), 100)
        self.assertTrue(all(types[a] != types[b] for a, b in zip(result, result[1:])))
        self.assertTrue(all(k.split(':')[0] not in [j.split(':')[0] for j in result[max(0,i-2):i]] for i,k in enumerate(result)))


if __name__ == '__main__':
    unittest.main()
