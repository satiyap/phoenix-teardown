"""Direct proof the WAL lands in OUR store.

create_channel awaits an invite-ack from every participant, so a single-agent
channel keeps the proof minimal while still exercising the real WAL path.
"""
import asyncio, sqlite3
from sqlstore import SqlKnowledgeStore
from ag2 import Agent
from ag2.network import Hub, Envelope, EV_TEXT

async def main():
    store = SqlKnowledgeStore("/tmp/spike01.db")
    hub = Hub(store, ttl_sweep_interval=0, expectation_sweep_interval=0)
    await hub.start()
    alice = await hub.register(Agent(name="alice"))
    meta = await hub.create_channel(
        creator_id=alice, manifest_type="conversation", participants=[alice])
    cid = meta.channel_id
    await hub.post_envelope(Envelope(
        channel_id=cid, sender_id=alice, audience=None,
        event_type=EV_TEXT, event_data={"text": "spike-proof"}))
    await hub.close()

    con = sqlite3.connect("/tmp/spike01.db")
    rows = con.execute("SELECT path, length(content) FROM blobs ORDER BY path").fetchall()
    print("rows in OUR sqlite db:")
    for p, n in rows: print(f"   {p}  ({n} b)")
    wal = [p for p, _ in rows if p.endswith("wal.jsonl")]
    print("\nWAL persisted in our store:", bool(wal), wal)
    if wal:
        b = con.execute("SELECT content FROM blobs WHERE path=?", (wal[0],)).fetchone()[0]
        b = b if isinstance(b, str) else b.decode()
        print("payload present:", "spike-proof" in b)
        print("no file WAL on disk:", not __import__("pathlib").Path("channels").exists())
asyncio.run(main())
