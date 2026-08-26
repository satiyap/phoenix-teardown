"""GATE 01b — two concurrent hubs racing on the same causation key.

Invariant (stated FIRST, before any implementation):
  For a given (channel_id, sender_id, causation_id), AT MOST ONE actor may
  execute the effect, no matter how many hubs observe NOT_FOUND concurrently.

A read-then-act lookup cannot provide this. This test proves the read-based
approach FAILS and that an atomic claim succeeds.
"""
import asyncio, sqlite3, tempfile, os
import pytest
from ag2 import Agent
from ag2.network import Hub, Envelope, EV_TEXT
from sqlstore import SqlKnowledgeStore

pytestmark = pytest.mark.asyncio


async def _seed(store):
    hub = await Hub.open(store, ttl_sweep_interval=0, expectation_sweep_interval=0)
    alice = await hub.register(Agent(name="alice"))
    bob = await hub.register(Agent(name="bob"))
    ch = await alice.open(type="conversation", target=["bob"])
    await ch.send("prompt")
    wal = await hub.read_wal(ch.channel_id)
    prompt = next(e for e in wal if e.event_type == EV_TEXT)
    return hub, ch.channel_id, bob.agent_id, prompt.envelope_id


# ---------------------------------------------------------------- known-bad
async def test_A_read_then_act_DOUBLE_EXECUTES(tmp_path):
    """NEGATIVE CONTROL: the read-based approach must be shown to fail."""
    store = SqlKnowledgeStore(str(tmp_path / "a.db"))
    hub, cid, bid, prompt_id = await _seed(store)
    effects: list[str] = []

    async def worker(tag):
        # read
        found = await hub.find_envelope_by_causation(cid, sender_id=bid,
                                                    causation_id=prompt_id)
        await asyncio.sleep(0)                     # yield: interleave the two
        if found is None:
            effects.append(tag)                    # act
            await hub.post_envelope(Envelope(
                channel_id=cid, sender_id=bid, audience=None,
                event_type=EV_TEXT, event_data={"text": tag},
                causation_id=prompt_id))
    try:
        await asyncio.gather(worker("w1"), worker("w2"))
        print(f"\n  read-then-act effects: {effects}")
        assert len(effects) == 2, "expected the KNOWN-BAD double execution"
    finally:
        await hub.close()


# ---------------------------------------------------------------- the claim
class EffectLedger:
    """Atomic claim. The UNIQUE index is the primitive, not the lookup."""

    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS effect_ledger ("
            " channel_id TEXT NOT NULL, sender_id TEXT NOT NULL,"
            " causation_id TEXT NOT NULL, status TEXT NOT NULL,"
            " PRIMARY KEY (channel_id, sender_id, causation_id))")

    def claim(self, cid, sid, caus) -> bool:
        """True iff THIS caller won the right to execute."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO effect_ledger"
            "(channel_id,sender_id,causation_id,status) VALUES(?,?,?,'pending')",
            (cid, sid, caus))
        return cur.rowcount == 1


async def test_B_atomic_claim_EXECUTES_ONCE(tmp_path):
    """Same race, claim-based. Exactly one winner."""
    store = SqlKnowledgeStore(str(tmp_path / "b.db"))
    hub, cid, bid, prompt_id = await _seed(store)
    ledger = EffectLedger(str(tmp_path / "ledger.db"))
    effects: list[str] = []

    async def worker(tag):
        if ledger.claim(cid, bid, prompt_id):      # claim BEFORE acting
            await asyncio.sleep(0)
            effects.append(tag)
    try:
        await asyncio.gather(*(worker(f"w{i}") for i in range(8)))
        print(f"  atomic-claim effects : {effects}")
        assert len(effects) == 1, f"exactly one winner required, got {effects}"
    finally:
        await hub.close()


async def test_C_claim_is_independent_of_channel_lifetime(tmp_path):
    """The ledger must NOT depend on message-log retention.

    Close the channel (AG2 prunes its index) and delete the WAL entirely.
    The claim must still hold, because the ledger is the authority.
    """
    store = SqlKnowledgeStore(str(tmp_path / "c.db"))
    hub, cid, bid, prompt_id = await _seed(store)
    ledger = EffectLedger(str(tmp_path / "ledger2.db"))
    assert ledger.claim(cid, bid, prompt_id) is True

    await hub.close_channel(cid, reason="test")
    await store.delete(f"/channels/{cid}/wal.jsonl")     # log GONE
    await hub.close()

    assert ledger.claim(cid, bid, prompt_id) is False, \
        "the claim must survive deletion of the message log"
    print("  claim survives channel close AND WAL deletion")


async def test_D_two_hub_instances_one_ledger(tmp_path):
    """Two independent Hub objects over one store, racing on one ledger."""
    store = SqlKnowledgeStore(str(tmp_path / "d.db"))
    hub, cid, bid, prompt_id = await _seed(store)
    await hub.close()

    h1 = await Hub.open(store, ttl_sweep_interval=0, expectation_sweep_interval=0)
    h2 = await Hub.open(store, ttl_sweep_interval=0, expectation_sweep_interval=0)
    ledger = EffectLedger(str(tmp_path / "ledger3.db"))
    wins = []
    try:
        for tag, _h in (("h1", h1), ("h2", h2)):
            if ledger.claim(cid, bid, prompt_id):
                wins.append(tag)
        print(f"  two-hub winners      : {wins}")
        assert len(wins) == 1
    finally:
        await h1.close(); await h2.close()
