"""SPIKE 01 GATE — does AG2's hub run on our storage, and does causation
dedupe survive channel termination?

Pass criterion (synthesis/scope-reconciliation.md §4):
  Replace AG2's file WAL with our append-only log, keeping the Envelope schema
  and hub contract intact, and demonstrate that causation dedupe does not
  degrade into "cannot tell" once terminal-channel pruning clears the index
  (OQ-024).
"""
import asyncio
import pytest
from ag2.network import Hub, Envelope, EV_TEXT
from ag2.knowledge import KnowledgeStore
from sqlstore import SqlKnowledgeStore

pytestmark = pytest.mark.asyncio


async def _hub():
    store = SqlKnowledgeStore()
    hub = Hub(store, ttl_sweep_interval=0, expectation_sweep_interval=0)
    await hub.start()
    return hub, store


async def test_1_store_satisfies_protocol():
    """Our store is structurally a KnowledgeStore — no fork, no subclass."""
    assert isinstance(SqlKnowledgeStore(), KnowledgeStore)


async def test_2_hub_runs_on_our_store():
    """The hub accepts our store by constructor injection and starts."""
    hub, store = await _hub()
    try:
        assert hub is not None
    finally:
        await hub.close()


async def test_3_wal_lands_in_our_store():
    """Envelopes are persisted through OUR append(), not a file."""
    hub, store = await _hub()
    try:
        await hub.register("alice")
        await hub.register("bob")
        ch = await hub.open_channel(
            opener_id="alice", participants=["alice", "bob"], channel_type="conversation")
        cid = ch if isinstance(ch, str) else getattr(ch, "channel_id", None)
        await hub.post_envelope(Envelope(
            channel_id=cid, sender_id="alice", audience=None,
            event_type=EV_TEXT, event_data={"text": "hello"}))
        raw = await store.read(f"/channels/{cid}/wal.jsonl")
        assert raw and "hello" in raw, f"WAL not in our store: {raw!r}"
        print(f"\n  WAL bytes in SQLite: {len(raw)}")
    finally:
        await hub.close()
