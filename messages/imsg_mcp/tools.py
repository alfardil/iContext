"""Pure tool implementations. server.py wraps these with @mcp.tool() decorators."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from imsg.models import Chat as ChatModel
from imsg.time_utils import dt_to_apple_ns
from imsg_mcp import embeddings, snapshot_queries
from imsg_mcp.index import VectorStore
from imsg_mcp.indexer import Indexer
from imsg_mcp.store_cache import Cache, resolve_name

log = logging.getLogger(__name__)


class ContactMatch(BaseModel):
    name: str
    handles: list[str]


class ChatInfo(BaseModel):
    guid: str
    identifier: str
    display_name: str | None
    style: str
    participants: list[str]
    last_message_at: str | None
    message_count: int | None = None


class SemanticHit(BaseModel):
    sent_at: str
    sender: str | None
    sender_name: str | None
    is_from_me: bool
    chat_guid: str
    text: str
    score: float


class ChatIndexStatus(BaseModel):
    chat_guid: str
    ready: bool
    indexed_messages: int
    total_messages: int
    indexed_pct: float
    last_indexed_at: str | None
    state: str
    last_error: str | None


class SemanticResult(BaseModel):
    hits: list[SemanticHit]
    chat_index_status: ChatIndexStatus


def find_contacts(cache: Cache, name: str, limit: int = 10) -> list[ContactMatch]:
    matches = resolve_name(cache.name_index, name, limit=limit)
    return [ContactMatch(name=n, handles=h) for n, h in matches]


def list_chats(cache: Cache, group_only: bool = False, limit: int = 50) -> list[ChatInfo]:
    summaries = snapshot_queries.chat_summaries(cache.snapshot())

    def recency(c: ChatModel) -> str:
        s = summaries.get(c.guid)
        return (s.last_message_at if s else None) or ""

    with cache.store() as store:
        chats = store.chats()
        if group_only:
            chats = [c for c in chats if c.style == "group"]
        chats_sorted = sorted(chats, key=recency, reverse=True)[:limit]
        return [_chat_to_info(c, summaries) for c in chats_sorted]


def _chat_to_info(c: ChatModel, summaries: dict[str, snapshot_queries.ChatSummary]) -> ChatInfo:
    s = summaries.get(c.guid)
    return ChatInfo(
        guid=c.guid,
        identifier=c.identifier,
        display_name=c.display_name,
        style=c.style,
        participants=list(c.participants),
        last_message_at=s.last_message_at if s else None,
        message_count=s.message_count if s else None,
    )


def semantic_search_messages(
    cache: Cache,
    vector_store: VectorStore,
    indexer: Indexer,
    *,
    query: str,
    chat_identifier: str | None = None,
    chat_guid: str | None = None,
    top_k: int = 20,
    from_only: bool = False,
    since: str | None = None,
    until: str | None = None,
    min_score: float = 0.30,
    wait_seconds: int = 30,
) -> SemanticResult:
    target = _resolve_chat_guid(cache, chat_identifier=chat_identifier, chat_guid=chat_guid)
    if target is None:
        # Synthesize an "absent" status with a placeholder guid so the model can react.
        return SemanticResult(
            hits=[],
            chat_index_status=_status(vector_store, chat_identifier or chat_guid or "<unknown>"),
        )

    indexer.submit_and_wait(target, wait_seconds=wait_seconds)
    status = _status(vector_store, target)
    if status.indexed_messages == 0:
        return SemanticResult(hits=[], chat_index_status=status)

    q_vec = embeddings.embed([query])[0]
    candidates = vector_store.knn(
        q_vec,
        chat_guid=target,
        k=max(top_k * 4, top_k),
        since_ns=_iso_to_ns(since),
        until_ns=_iso_to_ns(until),
    )

    score_by_guid = {g: s for g, s in candidates if s >= min_score}
    hits = _fetch_hits_by_guids(
        cache=cache,
        chat_guid=target,
        score_by_guid=score_by_guid,
        from_only=from_only,
        top_k=top_k,
    )
    return SemanticResult(hits=hits, chat_index_status=status)


def _fetch_hits_by_guids(
    cache: Cache,
    chat_guid: str,
    score_by_guid: dict[str, float],
    from_only: bool,
    top_k: int,
) -> list[SemanticHit]:
    """Assemble SemanticHits for the scored candidate GUIDs.

    Rows are bulk-fetched in a single query (snapshot_queries.fetch_messages_by_guids); here
    we decode attributedBody for rows whose plain `text` is empty and resolve sender names.
    """
    if not score_by_guid:
        return []
    from imsg.decoder import decode_attributed_body
    from imsg.time_utils import apple_to_dt

    rows = snapshot_queries.fetch_messages_by_guids(
        cache.snapshot(), chat_guid, score_by_guid.keys()
    )

    hits: list[SemanticHit] = []
    for r in rows:
        is_from_me = bool(r["msg_is_from_me"])
        if from_only and is_from_me:
            continue
        sent_at = apple_to_dt(r["msg_date"])
        if sent_at is None:
            continue
        text = r["msg_text"]
        if not (text and text.strip()):
            text, _ = decode_attributed_body(r["msg_body"])
        sender = None if is_from_me else r["handle_contact_id"]
        sender_name = cache.contacts.lookup(sender) if sender else None
        score = score_by_guid.get(r["msg_guid"], 0.0)
        hits.append(
            SemanticHit(
                sent_at=sent_at.isoformat(),
                sender=sender,
                sender_name=sender_name,
                is_from_me=is_from_me,
                chat_guid=chat_guid,
                text=text or "",
                score=round(score, 4),
            )
        )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top_k]


def index_chat(
    cache: Cache,
    vector_store: VectorStore,
    indexer: Indexer,
    *,
    chat_identifier: str | None = None,
    chat_guid: str | None = None,
    wait_seconds: int = 60,
) -> ChatIndexStatus:
    target = _resolve_chat_guid(cache, chat_identifier=chat_identifier, chat_guid=chat_guid)
    if target is None:
        return _status(vector_store, chat_identifier or chat_guid or "<unknown>")
    indexer.submit_and_wait(target, wait_seconds=wait_seconds)
    return _status(vector_store, target)


def index_status(
    cache: Cache,
    vector_store: VectorStore,
    *,
    chat_identifier: str | None = None,
    chat_guid: str | None = None,
) -> ChatIndexStatus | list[ChatIndexStatus]:
    if chat_identifier or chat_guid:
        target = _resolve_chat_guid(cache, chat_identifier=chat_identifier, chat_guid=chat_guid)
        return _status(vector_store, target or (chat_identifier or chat_guid or "<unknown>"))
    metas = vector_store.list_chat_meta()
    return [_meta_to_status(m) for m in metas]


def _resolve_chat_guid(
    cache: Cache,
    chat_identifier: str | None,
    chat_guid: str | None,
) -> str | None:
    if chat_guid:
        with cache.store() as store:
            for c in store.chats():
                if c.guid == chat_guid:
                    return chat_guid
        return None
    if chat_identifier:
        needle = chat_identifier.casefold()
        with cache.store() as store:
            for c in store.chats():
                if c.identifier.casefold() == needle:
                    return c.guid
            # fall back: handle appears in any chat's participants -> prefer 1:1
            candidates = [c for c in store.chats() if needle in {p.casefold() for p in c.participants}]
            direct = [c for c in candidates if c.style == "direct"]
            if direct:
                return direct[0].guid
            if candidates:
                return candidates[0].guid
        return None
    return None


def _status(vec: VectorStore, chat_guid: str) -> ChatIndexStatus:
    meta = vec.get_chat_meta(chat_guid)
    if meta is None:
        return ChatIndexStatus(
            chat_guid=chat_guid,
            ready=False,
            indexed_messages=0,
            total_messages=0,
            indexed_pct=0.0,
            last_indexed_at=None,
            state="absent",
            last_error=None,
        )
    return _meta_to_status(meta)


def _meta_to_status(meta: dict[str, Any]) -> ChatIndexStatus:
    indexed = int(meta.get("indexed_messages") or 0)
    total = int(meta.get("total_messages") or 0)
    state = str(meta.get("state") or "indexing")
    # Once state="ready", any minor drift (a new message arrived) shouldn't flip ready→false.
    # Treat state as the source of truth; indexed_pct conveys freshness.
    pct = (indexed / total) if total > 0 else (1.0 if state == "ready" else 0.0)
    return ChatIndexStatus(
        chat_guid=str(meta["chat_guid"]),
        ready=(state == "ready"),
        indexed_messages=indexed,
        total_messages=total,
        indexed_pct=round(min(1.0, max(0.0, pct)), 4),
        last_indexed_at=str(meta["last_indexed_at"]) if meta.get("last_indexed_at") else None,
        state=state,
        last_error=str(meta["last_error"]) if meta.get("last_error") else None,
    )


def _iso_to_ns(s: str | None) -> int | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt_to_apple_ns(dt)


# Re-export for typing checks — referenced from imsg_mcp.indexer's iteration helpers.
__all__ = [
    "ContactMatch",
    "ChatInfo",
    "ChatIndexStatus",
    "SemanticHit",
    "SemanticResult",
    "find_contacts",
    "list_chats",
    "semantic_search_messages",
    "index_chat",
    "index_status",
]
