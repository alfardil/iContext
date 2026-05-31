"""Unit tests for VectorStore.upsert_chat_meta partial-write semantics.

Guarded by importorskip: the default CI suite installs only the `dev` extra (the `mcp`
extra pulls torch and is host-only), so these skip there and run from the uv-managed
`.venv` that has sqlite-vec. They need no embeddings — only the chat_meta table.
"""

import pytest

pytest.importorskip("sqlite_vec")

from imsg_mcp.index import VectorStore  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = VectorStore(tmp_path / "vectors.db")
    try:
        yield s
    finally:
        s.close()


def test_insert_sets_only_given_columns_rest_default(store):
    store.upsert_chat_meta("c1", state="indexing")
    meta = store.get_chat_meta("c1")
    assert meta is not None
    assert meta["state"] == "indexing"
    assert meta["indexed_messages"] == 0
    assert meta["total_messages"] == 0
    assert meta["last_indexed_at"] is None
    assert meta["last_error"] is None


def test_update_preserves_untouched_columns(store):
    store.upsert_chat_meta("c1", indexed_messages=5, total_messages=10, state="indexing")
    store.upsert_chat_meta("c1", state="ready")  # touch only state
    meta = store.get_chat_meta("c1")
    assert meta["state"] == "ready"
    assert meta["indexed_messages"] == 5  # preserved
    assert meta["total_messages"] == 10  # preserved


def test_explicit_none_clears_a_column(store):
    store.upsert_chat_meta("c1", last_error="boom")
    assert store.get_chat_meta("c1")["last_error"] == "boom"
    store.upsert_chat_meta("c1", last_error=None)  # explicit clear
    assert store.get_chat_meta("c1")["last_error"] is None


def test_no_fields_just_ensures_row_exists(store):
    store.upsert_chat_meta("c1")  # no columns provided
    meta = store.get_chat_meta("c1")
    assert meta is not None
    assert meta["state"] == "indexing"  # table default


def test_list_chat_meta_returns_every_chat(store):
    store.upsert_chat_meta("c1", state="ready")
    store.upsert_chat_meta("c2", state="indexing")
    guids = {m["chat_guid"] for m in store.list_chat_meta()}
    assert guids == {"c1", "c2"}
