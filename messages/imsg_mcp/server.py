"""FastMCP server exposing iMessage tools.

Run via the FastMCP CLI:
    fastmcp run imsg_mcp/server.py --transport streamable-http --host 127.0.0.1 --port 5050

Or directly:
    python -m imsg_mcp.server
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from pydantic import Field

from imsg_mcp import embeddings as _embeddings
from imsg_mcp import tools as t
from imsg_mcp.index import VectorStore
from imsg_mcp.indexer import Indexer
from imsg_mcp.store_cache import Cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
)
log = logging.getLogger("imsg-mcp")

mcp = FastMCP(name="imsg")


_cache = Cache()
_vector_store = VectorStore()
_indexer = Indexer(
    vector_store=_vector_store,
    contacts=_cache.contacts,
    snapshot_path_provider=_cache.snapshot,
)

# import sentence-transformers on the main thread before worker threads
_embeddings.warmup()

# warm-start top-10 recent chats in the background
_indexer.warm_start(top_n=10, min_messages=50)


# tools
@mcp.tool
def find_contacts(
    name: str = Field(
        ...,
        description="Name substring to match against macOS Contacts (case-insensitive).",
    ),
    limit: int = Field(10, ge=1, le=50),
) -> list[t.ContactMatch]:
    """Resolve a person's name to one or more iMessage handles (phone numbers / emails).
    Returns up to `limit` matches sorted by relevance: exact > prefix > substring."""
    return t.find_contacts(_cache, name=name, limit=limit)


@mcp.tool
def list_chats(
    group_only: bool = Field(False, description="Restrict to group conversations."),
    limit: int = Field(50, ge=1, le=500),
) -> list[t.ChatInfo]:
    """List chats sorted by most recent activity. Use this to discover a group chat's
    GUID by display name, or to confirm a 1:1 chat exists for a given identifier."""
    return t.list_chats(_cache, group_only=group_only, limit=limit)


@mcp.tool
def semantic_search_messages(
    query: str = Field(
        ..., description="Natural-language description of what to find."
    ),
    chat_identifier: str | None = Field(
        None,
        description="Phone, email, or chat identifier — required if chat_guid not given.",
    ),
    chat_guid: str | None = Field(
        None,
        description="Specific chat GUID from list_chats — required if chat_identifier not given.",
    ),
    top_k: int = Field(20, ge=1, le=100),
    from_only: bool = Field(
        False,
        description="If True, exclude messages the user sent themselves.",
    ),
    since: str | None = Field(None, description="ISO date YYYY-MM-DD, UTC."),
    until: str | None = Field(None, description="ISO date YYYY-MM-DD, UTC."),
    min_score: float = Field(
        0.30, ge=0.0, le=1.0, description="Drop hits below this cosine similarity."
    ),
    wait_seconds: int = Field(
        30,
        ge=0,
        le=120,
        description="If the chat isn't indexed yet, block up to this many seconds while it indexes.",
    ),
) -> t.SemanticResult:
    """Search messages WITHIN A SINGLE CHAT by meaning. Works for both exact phrases
    ('spa', 'Friday at 8') and conceptual queries ('feeling overwhelmed', 'plans about traveling').

    A chat is indexed lazily on first use. If `chat_index_status.ready == false` and `hits`
    is empty, the chat is still indexing — report progress to the user and retry shortly.
    """
    return t.semantic_search_messages(
        _cache,
        _vector_store,
        _indexer,
        query=query,
        chat_identifier=chat_identifier,
        chat_guid=chat_guid,
        top_k=top_k,
        from_only=from_only,
        since=since,
        until=until,
        min_score=min_score,
        wait_seconds=wait_seconds,
    )


@mcp.tool
def index_chat(
    chat_identifier: str | None = Field(
        None, description="Phone, email, or chat identifier."
    ),
    chat_guid: str | None = Field(None, description="Specific chat GUID."),
    wait_seconds: int = Field(
        60,
        ge=0,
        le=600,
        description="Block up to N seconds while indexing; 0 = return immediately.",
    ),
) -> t.ChatIndexStatus:
    """Explicitly build the semantic index for one chat. Idempotent — already-indexed
    messages are skipped. Call proactively before a series of semantic queries to avoid
    the first-query wait."""
    return t.index_chat(
        _cache,
        _vector_store,
        _indexer,
        chat_identifier=chat_identifier,
        chat_guid=chat_guid,
        wait_seconds=wait_seconds,
    )


@mcp.tool
def index_status(
    chat_identifier: str | None = Field(
        None, description="Phone, email, or chat identifier."
    ),
    chat_guid: str | None = Field(None, description="Specific chat GUID."),
) -> t.ChatIndexStatus | list[t.ChatIndexStatus]:
    """Report per-chat index progress. With chat_identifier or chat_guid: returns one status.
    With neither: returns a list for every chat that has been indexed (or is indexing).
    """
    return t.index_status(
        _cache,
        _vector_store,
        chat_identifier=chat_identifier,
        chat_guid=chat_guid,
    )


def _strip_null_defaults(node: object) -> None:
    """Recursively remove `"default": null` entries from a JSON-schema dict.

    Google's gemini SDK (`com.google.genai.types.Schema.Builder.default_`) wraps incoming
    defaults in `Optional.of(value)`, which throws NPE on null. Pydantic emits
    `"default": null` for `Field(None, ...)` optional params — perfectly valid JSON Schema,
    but it crashes Spring AI's tool-callback bridge to Gemini. Stripping the key keeps the
    schema legal (omitted default == no default) and the field nullable via `anyOf [..., null]`.
    """
    if isinstance(node, dict):
        if "default" in node and node["default"] is None:
            del node["default"]
        for v in node.values():
            _strip_null_defaults(v)
    elif isinstance(node, list):
        for item in node:
            _strip_null_defaults(item)


def _sanitize_tool_schemas() -> None:
    """Walk the LocalProvider's component store and strip default:null from every schema.

    `fastmcp run` boots the server inside a running event loop, so `asyncio.run` blows up
    on `mcp.list_tools()`. Reach for the underlying component dict instead and mutate in place.
    """
    components = getattr(mcp._local_provider, "_components", {})
    for component in components.values():
        if isinstance(getattr(component, "parameters", None), dict):
            _strip_null_defaults(component.parameters)
        if isinstance(getattr(component, "output_schema", None), dict):
            _strip_null_defaults(component.output_schema)
    log.info("schemas sanitized for %d tool(s)", len(components))


_sanitize_tool_schemas()


if __name__ == "__main__":
    # Default transport for local dev. The `fastmcp` CLI overrides via `--transport`.
    mcp.run(transport="streamable-http", host="127.0.0.1", port=5050)
