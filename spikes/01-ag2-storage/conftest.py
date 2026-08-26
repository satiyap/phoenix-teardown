"""Swap AG2's MemoryKnowledgeStore for OUR SQLite store, and COUNT the calls.

If AG2's own network suite passes while every read/append goes through our
store, the hub contract is genuinely storage-agnostic. The counters are the
evidence that the swap took effect rather than being silently bypassed.
"""
import atexit
import ag2.knowledge as _k
import ag2.knowledge.memory as _mem
from sqlstore import SqlKnowledgeStore

CALLS = {"append": 0, "read": 0, "read_range": 0, "write": 0, "wal_paths": set()}


class CountingStore(SqlKnowledgeStore):
    async def append(self, path, content):
        CALLS["append"] += 1
        if path.endswith("wal.jsonl"):
            CALLS["wal_paths"].add(path)
        return await super().append(path, content)

    async def read(self, path):
        CALLS["read"] += 1
        return await super().read(path)

    async def read_range(self, path, start, end=None):
        CALLS["read_range"] += 1
        return await super().read_range(path, start, end)

    async def write(self, path, content):
        CALLS["write"] += 1
        return await super().write(path, content)


_mem.MemoryKnowledgeStore = CountingStore
_k.MemoryKnowledgeStore = CountingStore


@atexit.register
def _report():
    print("\n" + "=" * 62)
    print("SPIKE 01 — storage calls that went through OUR store")
    print("=" * 62)
    print(f"  append()      {CALLS['append']:>6}")
    print(f"  read()        {CALLS['read']:>6}")
    print(f"  read_range()  {CALLS['read_range']:>6}")
    print(f"  write()       {CALLS['write']:>6}")
    print(f"  distinct channel WALs written: {len(CALLS['wal_paths'])}")
    print("=" * 62)
