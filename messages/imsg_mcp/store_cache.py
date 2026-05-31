"""TTL-cached snapshot of `chat.db` plus ContactBook + reverse-name index.

Threading: a single `Cache` instance is shared across the MCP server. `snapshot()` and
`with store()` are safe to call from multiple threads; each call obtains its own
`MessageStore` (which holds a per-instance sqlite connection).
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from imsg import MessageStore, safe_copy_chatdb
from imsg.contacts import ContactBook

log = logging.getLogger(__name__)

SNAPSHOT_TTL_SECONDS = 300  # 5 min
SNAPSHOT_ROOT = Path("/tmp/imsg-mcp")
OLD_SNAPSHOT_GRACE_SECONDS = (
    120  # in-flight readers have this long to finish before deletion
)


class Cache:
    def __init__(self, snapshot_ttl: float = SNAPSHOT_TTL_SECONDS) -> None:
        self._snapshot_ttl = snapshot_ttl
        self._lock = threading.Lock()
        self._snapshot_path: Path | None = None
        self._snapshot_taken_at: float = 0.0

        self.contacts: ContactBook = ContactBook.from_default_sources()
        self.name_index: dict[str, list[str]] = _build_name_index(self.contacts)
        log.info(
            "ContactBook loaded: %d handles, %d distinct names",
            self.contacts.size,
            len(self.name_index),
        )

    def snapshot(self) -> Path:
        """Return a path to a snapshot of chat.db, refreshing if the TTL has expired.

        Every refresh writes to its own unique dir, so concurrent readers' open sqlite
        connections on the previous snapshot keep seeing a stable file. Old snapshot
        dirs are cleaned up after a grace window via a background timer.
        """
        now = time.monotonic()
        with self._lock:
            if (
                self._snapshot_path is None
                or (now - self._snapshot_taken_at) > self._snapshot_ttl
            ):
                old_path = self._snapshot_path
                dst_dir = SNAPSHOT_ROOT / f"snap-{int(time.time() * 1000)}"
                self._snapshot_path = safe_copy_chatdb(dst_dir=dst_dir)
                self._snapshot_taken_at = now
                log.info("Snapshot refreshed at %s", self._snapshot_path)
                if old_path is not None:
                    _schedule_cleanup(old_path.parent, delay=OLD_SNAPSHOT_GRACE_SECONDS)
            return self._snapshot_path

    @contextmanager
    def store(self) -> Iterator[MessageStore]:
        """Open a fresh MessageStore over the cached snapshot. NOT thread-shared."""
        snap = self.snapshot()
        s = MessageStore(snap, contacts=self.contacts)
        try:
            yield s
        finally:
            s.close()


def _build_name_index(book: ContactBook) -> dict[str, list[str]]:
    """Reverse map: contact name (lowercase) -> list of handles (phones + emails).

    ContactBook exposes only forward lookup via `.lookup(handle)`. We reach into the
    populated `_phones` / `_emails` maps for the reverse index — same package, acceptable.
    """
    name_to_handles: dict[str, list[str]] = {}
    for handle, name in book._phones.items():
        name_to_handles.setdefault(name.casefold(), []).append(handle)
    for handle, name in book._emails.items():
        name_to_handles.setdefault(name.casefold(), []).append(handle)

    for name, handles in name_to_handles.items():
        name_to_handles[name] = list(dict.fromkeys(handles))
    return name_to_handles


def resolve_name(
    name_index: dict[str, list[str]], query: str, limit: int = 10
) -> list[tuple[str, list[str]]]:
    """Substring match against the reverse-name index.

    Ranking: exact match > prefix > substring > alpha. Returns (display_name, handles)
    tuples; display_name is the first canonical-cased version we find.
    """
    q = query.casefold().strip()
    if not q:
        return []
    exact: list[str] = []
    prefix: list[str] = []
    substr: list[str] = []
    for name in name_index:
        if name == q:
            exact.append(name)
        elif name.startswith(q):
            prefix.append(name)
        elif q in name:
            substr.append(name)
    ranked = exact + sorted(prefix) + sorted(substr)
    return [(_canon_case(n), name_index[n]) for n in ranked[:limit]]


def _canon_case(folded: str) -> str:
    """Casefolded -> title-case best-effort. Just title-cases each whitespace token."""
    return " ".join(
        part.capitalize() if part.isalpha() else part for part in folded.split()
    )


def _schedule_cleanup(dir_to_remove: Path, delay: float) -> None:
    def _rm() -> None:
        try:
            shutil.rmtree(dir_to_remove, ignore_errors=True)
            log.debug("removed old snapshot dir %s", dir_to_remove)
        except Exception:
            pass

    t = threading.Timer(delay, _rm)
    t.daemon = True
    t.start()
