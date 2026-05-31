# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`imsg` is a strongly-typed Python library that reads `~/Library/Messages/chat.db`. Its reason to exist: from macOS Ventura on, message text lives in the `attributedBody` BLOB (a NeXT-era `typedstream` archive), not the `text` column — a naive `SELECT text FROM message` misses ~89% of messages. This codebase decodes that BLOB plus edit/unsend history, tapbacks, app balloons, and contact names. Used as a library only — `imsg_mcp` is the sole consumer.

## Commands

```bash
pip install -e ".[dev]"      # editable install with pytest/mypy/ruff

pytest                       # full suite
pytest tests/test_e2e.py     # one file
pytest tests/test_e2e.py::test_name -q   # one test

mypy imsg                    # strict mode (configured in pyproject.toml)
ruff check imsg tests        # lint (line-length 110)
```

## Architecture

Data flows: **db.py** (snapshot + raw SQL) → **queries.py** (`MessageStore`, the high-level API) → **decoder.py** (BLOB decoding) → **models.py** (frozen Pydantic v2).

Key cross-cutting facts that aren't obvious from any single file:

- **Read path is snapshot-based.** `safe_copy_chatdb()` copies `chat.db` + `-wal` + `-shm` to `/tmp/imsg`, then runs `PRAGMA wal_checkpoint(TRUNCATE)` *on the copy* so reads see committed-but-unflushed messages. The live DB is opened `?mode=ro&immutable=1`. Reading the source requires macOS **Full Disk Access** for the running binary (Terminal/Python); a `PermissionError` is surfaced as `FullDiskAccessRequired` with remediation text.

- **Text decoding has a fallback chain** (`decoder.decode_attributed_body`): try `typedstream.unarchive_from_data` first; on any exception fall back to `_byte_scan_nsstring`, which locates `b"NSString"` and reads a length-prefixed UTF-8 string. `Message.decoded_from_attributed_body` records which path was used. `queries._row_to_message` prefers the plain `text` column only when non-empty, else decodes the BLOB.

- **`MessageStore.messages()` is a two-pass generator.** Pass 1 (`_collect_reactions`) scans the same SQL to fold tapback rows (`associated_message_type` in the tapback ranges) into `reactions_by_target` keyed by target GUID; pass 2 streams real messages in batches of `_BATCH` (500), bulk-fetching attachments per batch and attaching reactions. Tapbacks and group-event rows (`item_type != 0`) are filtered out of the main stream unless `include_group_events=True`. Note both passes run `MESSAGE_SQL` separately.

- **Timestamps are Apple-epoch (2001-01-01).** `time_utils.apple_to_dt` disambiguates three encodings by magnitude: `message.date` is int nanoseconds; `message_summary_info` edit timestamps (`d`) are float seconds — the `_NS_THRESHOLD` (1e11) split handles this. All returned datetimes are UTC.

- **Tapback codes** (`constants.py` / `models.TapbackType`): add = 2000–2006, remove = add + 1000 (3000–3006). `from_raw` and `is_tapback_type` both normalize the 3000 range back down. `associated_message_guid` may be `p:N/<guid>` (part index) or bare `<guid>` — split by `_split_assoc_target`.

- **Edits/unsends** live in the `message_summary_info` binary plist (`decode_edit_summary`): `ec` maps part index → list of edit entries (each with a nested `typedstream` text blob `t` and timestamp `d`); `rp` lists retracted (unsent) part indexes.

- **Contacts** (`contacts.py`): `ContactBook.from_default_sources()` snapshots every `AddressBook/Sources/*/AddressBook-v22.abcddb` (the top-level aggregator DB is ignored), checkpoints WAL, and aggregates phone/email → name. Phone matching normalizes to `+digits` with a bare-10-digit → `+1` US fallback.

- **All models are frozen** (`_Frozen` base, `ConfigDict(frozen=True)`) and use tuples, not lists, for collections — treat `Message` and friends as immutable.

## Testing notes

`tests/test_e2e.py` builds a real in-memory-schema chat.db in `tmp_path` (see `_SCHEMA`) and drives `MessageStore` end to end. Binary fixtures `tests/fixtures/sample_attributed_body.bin` and `sample_edit_summary.bin` are real captured BLOBs used to test the decoders. There is no networked or live-DB dependency in the test suite.
