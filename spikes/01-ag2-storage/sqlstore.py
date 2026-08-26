"""A KnowledgeStore over SQLite — stand-in for our append-only log.

Proves the AG2 hub runs on OUR storage rather than its file WAL. SQLite is used
so the spike needs no server; the semantics exercised (atomic append returning a
byte offset, byte-range reads, durable rows) are the same ones Postgres gives.
"""
from __future__ import annotations
import sqlite3
from ag2.knowledge.base import ChangeCallback, ChangeSubscription


class NoopSub:
    async def unsubscribe(self) -> None: ...


class SqlKnowledgeStore:
    """Path-addressed blob store backed by a single table."""

    def __init__(self, path: str = ":memory:") -> None:
        self._db = sqlite3.connect(path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS blobs ("
            " path TEXT PRIMARY KEY,"
            " content BLOB NOT NULL DEFAULT x''"
            ")"
        )
        self._db.commit()

    # --- reads -----------------------------------------------------------
    async def read(self, path: str) -> str | None:
        r = self._db.execute("SELECT content FROM blobs WHERE path=?", (path,)).fetchone()
        if r is None:
            return None
        return r[0] if isinstance(r[0], str) else r[0].decode()

    async def read_range(self, path: str, start: int, end: int | None = None) -> str:
        r = self._db.execute("SELECT content FROM blobs WHERE path=?", (path,)).fetchone()
        if r is None:
            return ""
        blob = r[0]
        if isinstance(blob, str):          # SQLite || can coerce BLOB -> TEXT
            blob = blob.encode()
        return blob[start:end if end is not None else len(blob)].decode()

    async def exists(self, path: str) -> bool:
        return self._db.execute("SELECT 1 FROM blobs WHERE path=?", (path,)).fetchone() is not None

    async def list(self, path: str = "/") -> list[str]:
        if not path.endswith("/"):
            path += "/"
        rows = self._db.execute("SELECT path FROM blobs WHERE path LIKE ?", (path + "%",)).fetchall()
        out: set[str] = set()
        for (p,) in rows:
            rest = p[len(path):]
            if not rest:
                continue
            head, sep, _ = rest.partition("/")
            out.add(head + ("/" if sep else ""))
        return sorted(out)

    # --- writes ----------------------------------------------------------
    async def write(self, path: str, content: str) -> None:
        self._db.execute(
            "INSERT INTO blobs(path, content) VALUES(?,?) "
            "ON CONFLICT(path) DO UPDATE SET content=excluded.content",
            (path, content.encode()),
        )
        self._db.commit()

    async def append(self, path: str, content: str) -> int:
        """Atomic append returning the byte offset written at.

        The single UPDATE...RETURNING is the analogue of AX's MAX(step)+1
        computed inside the insert transaction: the offset is derived by the
        database, so two concurrent appends cannot claim the same one.
        """
        cur = self._db.execute(
            "INSERT INTO blobs(path, content) VALUES(?, x'') "
            "ON CONFLICT(path) DO NOTHING", (path,))
        row = self._db.execute(
            "UPDATE blobs SET content = CAST(content AS BLOB) || CAST(? AS BLOB) WHERE path=? "
            "RETURNING length(content) - length(?)",
            (content.encode(), path, content.encode()),
        ).fetchone()
        self._db.commit()
        return int(row[0])

    async def delete(self, path: str) -> None:
        self._db.execute("DELETE FROM blobs WHERE path=?", (path,))
        self._db.commit()

    async def on_change(self, path: str, callback: ChangeCallback) -> ChangeSubscription:
        return NoopSub()
