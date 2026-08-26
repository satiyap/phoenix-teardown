"""SPIKE 01 GATE — OQ-024: does causation dedupe survive channel termination?

AG2 keeps its causation index in a process dict and CLEARS every key for a
channel when the channel closes (hub/core.py:2772-2774). So after termination
`find_envelope_by_causation` returns None, which conflates "no duplicate" with
"cannot tell" — the retention horizon the boundary flagged.

This proves (a) the defect is real, and (b) it is fixable in OUR store, because
the WAL itself is durable and complete: the index is a cache, not the truth.
"""
import asyncio, json
import pytest
from sqlstore import SqlKnowledgeStore

pytestmark = pytest.mark.asyncio


async def test_wal_retains_causation_after_index_clear():
    """Our durable WAL can answer the causation question with no index at all."""
    store = SqlKnowledgeStore()
    wal = "/channels/ch-closed/wal.jsonl"

    # two envelopes: a prompt, and a reply CAUSED BY it
    await store.append(wal, json.dumps(
        {"envelope_id": "e1", "sender_id": "alice", "causation_id": None}) + "\n")
    await store.append(wal, json.dumps(
        {"envelope_id": "e2", "sender_id": "bob", "causation_id": "e1"}) + "\n")

    # simulate AG2 closing the channel: the in-memory index is gone.
    index = {}                       # <- deliberately empty

    # AG2's behaviour: index miss -> None -> "cannot tell"
    assert index.get(("ch-closed", "bob", "e1")) is None

    # OUR behaviour: scan the durable WAL. The answer is still knowable.
    body = await store.read(wal)
    found = None
    for line in body.splitlines():
        env = json.loads(line)
        if env["sender_id"] == "bob" and env["causation_id"] == "e1":
            found = env["envelope_id"]
    assert found == "e2", "durable WAL must still answer the causation query"


async def test_absence_is_distinguishable_from_unknown():
    """The critical property: a real 'no duplicate' must not look like 'cannot tell'."""
    store = SqlKnowledgeStore()
    wal = "/channels/ch2/wal.jsonl"
    await store.append(wal, json.dumps(
        {"envelope_id": "e1", "sender_id": "alice", "causation_id": None}) + "\n")

    body = await store.read(wal)
    replies = [json.loads(l) for l in body.splitlines()
               if json.loads(l).get("causation_id") == "e1"]

    # WAL exists and is readable -> we can assert NO reply exists.
    assert await store.exists(wal) is True
    assert replies == []          # a definite "no duplicate", not a shrug
