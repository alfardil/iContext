"""Per-chat background indexer.

Submit a chat for indexing; one worker per chat at a time, up to N workers total.
`submit_and_wait` blocks up to `wait_seconds` for the chat to finish.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from imsg import MessageStore
from imsg.contacts import ContactBook
from imsg.time_utils import dt_to_apple_ns
from imsg_mcp import embeddings, snapshot_queries
from imsg_mcp.index import VectorStore, message_guids_for_chat

if TYPE_CHECKING:
    from imsg.models import Chat

log = logging.getLogger(__name__)

DEFAULT_WORKERS = 2
BATCH = 256


class Indexer:
    def __init__(
        self,
        vector_store: VectorStore,
        contacts: ContactBook,
        snapshot_path_provider: Callable[[], Path],
        max_workers: int = DEFAULT_WORKERS,
    ) -> None:
        self._vec = vector_store
        self._contacts = contacts
        self._snapshot_path_provider = snapshot_path_provider
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="imsg-idx"
        )
        self._lock = threading.Lock()
        self._in_flight: dict[str, Future[None]] = {}
        self._events: dict[str, threading.Event] = {}

    def submit(self, chat_guid: str) -> Future[None]:
        with self._lock:
            fut = self._in_flight.get(chat_guid)
            if fut is not None and not fut.done():
                return fut
            ev = self._events.setdefault(chat_guid, threading.Event())
            ev.clear()
            fut = self._executor.submit(self._run_job, chat_guid, ev)
            self._in_flight[chat_guid] = fut
            return fut

    def submit_and_wait(self, chat_guid: str, wait_seconds: float) -> None:
        fut = self.submit(chat_guid)
        try:
            fut.result(timeout=wait_seconds)
        except Exception:
            pass

    def warm_start(self, top_n: int = 10, min_messages: int = 50) -> None:
        """Submit the top-N most-recently-active chats with ≥ min_messages messages."""
        try:
            snap = self._snapshot_path_provider()
        except Exception as exc:
            log.warning("warm_start: cannot snapshot chat.db: %s", exc)
            return
        guids = snapshot_queries.recent_chat_guids(
            snap, min_messages=min_messages, limit=top_n
        )
        log.info("warm-start: indexing top %d chats…", len(guids))
        for guid in guids:
            self.submit(guid)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run_job(self, chat_guid: str, done_event: threading.Event) -> None:
        start = time.monotonic()
        snap: Path
        try:
            snap = self._snapshot_path_provider()
        except Exception as exc:
            self._vec.upsert_chat_meta(chat_guid, state="error", last_error=str(exc))
            done_event.set()
            return

        # in progress
        self._vec.upsert_chat_meta(chat_guid, state="indexing", last_error=None)

        try:
            embeddings.warmup()
            with MessageStore(snap, contacts=self._contacts) as store:
                total = snapshot_queries.message_count_for_chat(snap, chat_guid)
                already = message_guids_for_chat(self._vec, chat_guid)
                indexed_count = len(already)
                self._vec.upsert_chat_meta(
                    chat_guid,
                    indexed_messages=indexed_count,
                    total_messages=total,
                )

                last_indexed_dt = _get_last_indexed_dt(self._vec, chat_guid)
                stream = store.messages(chat_guid=chat_guid, since=last_indexed_dt)

                batch_texts: list[str] = []
                batch_meta: list[tuple[str, int]] = []  # (msg_guid, sent_at_ns)
                newest_dt: datetime | None = last_indexed_dt

                for msg in stream:
                    if msg.guid in already:
                        continue
                    text = (msg.text or "").strip()
                    if not text:
                        continue
                    batch_texts.append(text)
                    batch_meta.append((msg.guid, dt_to_apple_ns(msg.sent_at)))
                    if msg.sent_at and (newest_dt is None or msg.sent_at > newest_dt):
                        newest_dt = msg.sent_at
                    if len(batch_texts) >= BATCH:
                        self._flush(chat_guid, batch_texts, batch_meta)
                        indexed_count += len(batch_texts)
                        batch_texts.clear()
                        batch_meta.clear()
                        self._vec.upsert_chat_meta(
                            chat_guid,
                            indexed_messages=indexed_count,
                            last_indexed_at=(
                                newest_dt.isoformat() if newest_dt else None
                            ),
                        )

                if batch_texts:
                    self._flush(chat_guid, batch_texts, batch_meta)
                    indexed_count += len(batch_texts)

                self._vec.upsert_chat_meta(
                    chat_guid,
                    indexed_messages=indexed_count,
                    total_messages=max(total, indexed_count),
                    last_indexed_at=newest_dt.isoformat() if newest_dt else None,
                    state="ready",
                    last_error=None,
                )
            elapsed = time.monotonic() - start
            log.info(
                "indexed chat %s: %d msgs in %.1fs",
                chat_guid,
                indexed_count,
                elapsed,
            )
        except Exception as exc:
            log.exception("indexing chat %s failed", chat_guid)
            self._vec.upsert_chat_meta(chat_guid, state="error", last_error=str(exc))
            raise
        finally:
            done_event.set()

    def _flush(
        self,
        chat_guid: str,
        texts: list[str],
        meta: list[tuple[str, int]],
    ) -> None:
        vecs = embeddings.embed(texts)
        rows = [(g, ts, vecs[i]) for i, (g, ts) in enumerate(meta)]
        self._vec.upsert_batch(chat_guid, rows)


def _get_last_indexed_dt(store: VectorStore, chat_guid: str) -> datetime | None:
    meta = store.get_chat_meta(chat_guid)
    if not meta:
        return None
    raw = meta.get("last_indexed_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


__all__ = ["Indexer", "Chat"]
