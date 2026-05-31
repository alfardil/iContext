"""sqlite-vec backed vector store at ~/.imsg-mcp/vectors.db.

Schema:
  messages  (msg_guid PK, chat_guid, sent_at_ns, vec_rowid)
  chat_meta (chat_guid PK, indexed_messages, total_messages,
             last_indexed_at, last_error, state)
  vec_index VIRTUAL TABLE vec0(embedding FLOAT[384])

KNN: join vec_index → messages, filter by chat_guid + sent_at window. Over-fetch by
4× to compensate for post-filter selectivity (caller's responsibility).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

DEFAULT_VECTOR_DB_DIR = Path.home() / ".imsg-mcp"
DEFAULT_VECTOR_DB_PATH = DEFAULT_VECTOR_DB_DIR / "vectors.db"


class _Unchanged:
    pass


_UNCHANGED = _Unchanged()


def _open(path: Path) -> sqlite3.Connection:
    import sqlite_vec

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  msg_guid    TEXT PRIMARY KEY,
  chat_guid   TEXT NOT NULL,
  sent_at_ns  INTEGER NOT NULL,
  vec_rowid   INTEGER NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_guid);

CREATE TABLE IF NOT EXISTS chat_meta (
  chat_guid          TEXT PRIMARY KEY,
  indexed_messages   INTEGER NOT NULL DEFAULT 0,
  total_messages     INTEGER NOT NULL DEFAULT 0,
  last_indexed_at    TEXT,
  last_error         TEXT,
  state              TEXT NOT NULL DEFAULT 'indexing'
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_index USING vec0(embedding FLOAT[384]);
"""


class VectorStore:
    def __init__(self, path: Path = DEFAULT_VECTOR_DB_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn = _open(path)
        with self._lock:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def upsert_batch(
        self,
        chat_guid: str,
        rows: list[tuple[str, int, "np.ndarray"]],
    ) -> None:
        """rows = list of (msg_guid, sent_at_ns, embedding[float32 384])."""
        if not rows:
            return
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN")
                for msg_guid, sent_at_ns, vec in rows:
                    existing = cur.execute(
                        "SELECT vec_rowid FROM messages WHERE msg_guid = ?",
                        (msg_guid,),
                    ).fetchone()
                    if existing is not None:
                        cur.execute(
                            "DELETE FROM vec_index WHERE rowid = ?",
                            (existing["vec_rowid"],),
                        )
                    cur.execute(
                        "INSERT INTO vec_index(embedding) VALUES (?)",
                        (_to_blob(vec),),
                    )
                    vec_rowid = cur.lastrowid
                    cur.execute(
                        """INSERT INTO messages(msg_guid, chat_guid, sent_at_ns, vec_rowid)
                             VALUES (?, ?, ?, ?)
                           ON CONFLICT(msg_guid) DO UPDATE SET
                             chat_guid  = excluded.chat_guid,
                             sent_at_ns = excluded.sent_at_ns,
                             vec_rowid  = excluded.vec_rowid""",
                        (msg_guid, chat_guid, sent_at_ns, vec_rowid),
                    )
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise

    def knn(
        self,
        query_vec: "np.ndarray",
        chat_guid: str,
        k: int,
        since_ns: int | None = None,
        until_ns: int | None = None,
    ) -> list[tuple[str, float]]:
        """Return [(msg_guid, cosine_similarity)] sorted desc."""
        with self._lock:
            cur = self._conn.execute(
                """SELECT m.msg_guid AS msg_guid, v.distance AS distance
                     FROM vec_index v
                     JOIN messages   m ON m.vec_rowid = v.rowid
                    WHERE v.embedding MATCH ? AND v.k = ?
                      AND m.chat_guid = ?
                      AND (? IS NULL OR m.sent_at_ns >= ?)
                      AND (? IS NULL OR m.sent_at_ns <  ?)
                 ORDER BY v.distance""",
                (
                    _to_blob(query_vec),
                    k,
                    chat_guid,
                    since_ns,
                    since_ns,
                    until_ns,
                    until_ns,
                ),
            )
            out: list[tuple[str, float]] = []
            for r in cur:
                # L2 distance on unit vectors → cosine sim = 1 - 0.5 * d^2
                d = float(r["distance"])
                sim = max(0.0, min(1.0, 1.0 - 0.5 * d * d))
                out.append((str(r["msg_guid"]), sim))
            return out

    def get_chat_meta(self, chat_guid: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM chat_meta WHERE chat_guid = ?",
                (chat_guid,),
            ).fetchone()
            return dict(row) if row else None

    def list_chat_meta(self) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM chat_meta")
            return [dict(r) for r in cur]

    def upsert_chat_meta(
        self,
        chat_guid: str,
        *,
        indexed_messages: int | _Unchanged = _UNCHANGED,
        total_messages: int | _Unchanged = _UNCHANGED,
        last_indexed_at: str | None | _Unchanged = _UNCHANGED,
        last_error: str | None | _Unchanged = _UNCHANGED,
        state: str | _Unchanged = _UNCHANGED,
    ) -> None:
        """Insert or update one chat_meta row, writing only the columns passed explicitly.

        Columns left at their default (_UNCHANGED) keep their current value; pass an explicit
        None to clear last_indexed_at / last_error. This runs as a single INSERT … ON CONFLICT
        statement — no read-then-write, so two workers touching the same chat can't clobber
        each other, and absent columns fall back to the table's defaults on first insert.
        """
        provided = {
            col: value
            for col, value in (
                ("indexed_messages", indexed_messages),
                ("total_messages", total_messages),
                ("last_indexed_at", last_indexed_at),
                ("last_error", last_error),
                ("state", state),
            )
            if not isinstance(value, _Unchanged)
        }
        columns = ["chat_guid", *provided]
        values = ", ".join(f":{col}" for col in columns)
        if provided:
            conflict = "DO UPDATE SET " + ", ".join(f"{col} = excluded.{col}" for col in provided)
        else:
            conflict = "DO NOTHING"
        sql = (
            f"INSERT INTO chat_meta ({', '.join(columns)}) VALUES ({values}) "
            f"ON CONFLICT(chat_guid) {conflict}"
        )
        params: dict[str, object] = {"chat_guid": chat_guid, **provided}
        with self._lock:
            self._conn.execute(sql, params)


def _to_blob(vec: "np.ndarray") -> bytes:
    import numpy as np

    if vec.dtype != np.float32:
        vec = vec.astype(np.float32)
    return vec.tobytes()


def message_guids_for_chat(store: VectorStore, chat_guid: str) -> set[str]:
    """Return the set of msg_guids already indexed for the given chat."""
    with store._lock:
        cur = store._conn.execute(
            "SELECT msg_guid FROM messages WHERE chat_guid = ?",
            (chat_guid,),
        )
        return {str(r["msg_guid"]) for r in cur}


def iter_indexed_chats(store: VectorStore) -> Iterable[str]:
    with store._lock:
        cur = store._conn.execute("SELECT DISTINCT chat_guid FROM messages")
        for r in cur:
            yield str(r["chat_guid"])
