import asyncio

import pytest

import bot


class _FakeTask:
    def __init__(self, result):
        self._result = result

    def done(self):
        return True

    def cancelled(self):
        return False

    def result(self):
        return self._result


@pytest.mark.asyncio
async def test_refresh_tip_evs_uses_partial_results_on_timeout(monkeypatch):
    created = []

    def fake_create_task(coro):
        created.append(coro)
        try:
            coro.close()
        except Exception:
            pass
        idx = len(created)
        if idx == 1:
            return _FakeTask(("match-1", 6.2))
        return _FakeTask(("match-2", -1.5))

    def fake_gather(*args, **kwargs):
        async def _pending():
            return []

        return _pending()

    async def fake_wait_for(awaitable, timeout):
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(bot.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(bot.asyncio, "gather", fake_gather)
    monkeypatch.setattr(bot.asyncio, "wait_for", fake_wait_for)

    tips = [
        {"match_id": "match-1", "event_id": "match-1", "edge_v2": {"outcome": "Home Win"}, "ev": 1.0},
        {"match_id": "match-2", "event_id": "match-2", "edge_v2": {"outcome": "Away Win"}, "ev": 2.0},
    ]

    refreshed = await bot._refresh_tip_evs(tips)

    assert [tip["match_id"] for tip in refreshed] == ["match-1"]
    assert refreshed[0]["ev"] == 6.2
