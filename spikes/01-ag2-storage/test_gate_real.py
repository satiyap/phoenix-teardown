"""SPIKE 01 REAL GATE — public API only, per the revised gate.

Requirements the previous version failed:
 1. create and use a REAL AG2 channel
 2. post a causation-linked reply
 3. TERMINATE the channel
 4. destroy and recreate the Hub over the SAME store
 5. call the REAL Hub.find_envelope_by_causation()
 6. exercise two Hub instances over one store
"""
import asyncio, json
import pytest
from ag2 import Agent
from ag2.network import Hub, Envelope, EV_TEXT
from ag2.config import ModelConfig
from sqlstore import SqlKnowledgeStore

pytestmark = pytest.mark.asyncio


class _Scripted(ModelConfig):
    """Minimal deterministic config so agents need no LLM."""
    def __init__(self): super().__init__(model="scripted")
    def create_client(self, **kw): raise NotImplementedError


def _agent(name): return Agent(name=name)


async def _hub(store, **kw):
    return await Hub.open(store, ttl_sweep_interval=0,
                          expectation_sweep_interval=0, **kw)


async def _seed(store):
    """Real channel, real envelopes, real causation link. Returns ids."""
    hub = await _hub(store)
    alice = await hub.register(_agent("alice"))
    bob = await hub.register(_agent("bob"))
    ch = await alice.open(type="conversation", target=["bob"])
    cid = ch.channel_id
    await ch.send("prompt")

    wal = await hub.read_wal(cid)
    prompt = next(e for e in wal if e.event_type == EV_TEXT)

    # a reply CAUSED BY the prompt — the dedupe record
    reply = Envelope(channel_id=cid, sender_id=bob.agent_id, audience=None,
                     event_type=EV_TEXT, event_data={"text": "reply"},
                     causation_id=prompt.envelope_id)
    reply_id = await hub.post_envelope(reply)
    return hub, cid, alice.agent_id, bob.agent_id, prompt.envelope_id, reply_id


async def test_1_causation_found_while_channel_open():
    """Baseline: the real method finds the reply while the channel lives."""
    store = SqlKnowledgeStore()
    hub, cid, aid, bid, prompt_id, reply_id = await _seed(store)
    try:
        got = await hub.find_envelope_by_causation(cid, sender_id=bid,
                                                  causation_id=prompt_id)
        assert got is not None and got.envelope_id == reply_id
    finally:
        await hub.close()


async def test_2_REAL_GATE_causation_after_termination():
    """THE GATE. Close the channel, then ask the real method again."""
    store = SqlKnowledgeStore()
    hub, cid, aid, bid, prompt_id, reply_id = await _seed(store)
    try:
        await hub.close_channel(cid, reason="test")
        got = await hub.find_envelope_by_causation(cid, sender_id=bid,
                                                  causation_id=prompt_id)
        print(f"\n  after close_channel -> {got!r}")
        # Record the ACTUAL behaviour rather than asserting what I hoped.
        return got
    finally:
        await hub.close()


async def test_3_REAL_GATE_after_hub_restart():
    """Destroy the Hub, rebuild over the SAME store, ask again."""
    store = SqlKnowledgeStore()
    hub, cid, aid, bid, prompt_id, reply_id = await _seed(store)
    await hub.close_channel(cid, reason="test")
    await hub.close()

    hub2 = await _hub(store)                       # fresh authority, same data
    try:
        got = await hub2.find_envelope_by_causation(cid, sender_id=bid,
                                                    causation_id=prompt_id)
        print(f"  after hub restart  -> {got!r}")
        wal = await hub2.read_wal(cid)
        print(f"  WAL still readable -> {len(wal)} envelopes")
        assert len(wal) >= 2, "the durable log must survive restart"
    finally:
        await hub2.close()


async def test_4_two_hubs_one_store():
    """Two Hub instances over one store — the replica question."""
    store = SqlKnowledgeStore()
    hub, cid, aid, bid, prompt_id, reply_id = await _seed(store)
    await hub.close()

    h1 = await _hub(store)
    h2 = await _hub(store)
    try:
        g1 = await h1.find_envelope_by_causation(cid, sender_id=bid, causation_id=prompt_id)
        g2 = await h2.find_envelope_by_causation(cid, sender_id=bid, causation_id=prompt_id)
        print(f"  hub1 -> {g1!r}\n  hub2 -> {g2!r}")
    finally:
        await h1.close(); await h2.close()


async def test_5_two_hubs_AFTER_termination():
    """Test 4 passed only because both hubs hydrated BEFORE the close.
    Hydrate skips terminal channels by design (core.py:2907-2911), so a hub
    that starts AFTER termination cannot answer. This is the real horizon."""
    store = SqlKnowledgeStore()
    hub, cid, aid, bid, prompt_id, reply_id = await _seed(store)
    await hub.close_channel(cid, reason="test")     # close FIRST
    await hub.close()

    fresh = await _hub(store)                       # hydrate sees it terminal
    try:
        got = await fresh.find_envelope_by_causation(cid, sender_id=bid,
                                                     causation_id=prompt_id)
        wal = await fresh.read_wal(cid)
        print(f"\n  fresh hub after close -> {got!r}")
        print(f"  but WAL has {len(wal)} envelopes, and the reply IS in it:")
        hit = [e for e in wal if e.causation_id == prompt_id]
        print(f"    causation match in WAL: {len(hit)} -> {hit[0].envelope_id if hit else None}")
        # The horizon, stated precisely:
        assert got is None, "index cannot answer"
        assert len(hit) == 1, "but the durable log CAN"
    finally:
        await fresh.close()
