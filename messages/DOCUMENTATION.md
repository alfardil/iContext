# `imsg` — iMessage chat.db Reader

Strongly-typed Python library + CLI that reads **every** message in `~/Library/Messages/chat.db`, including the ~89% of messages that a naive `SELECT text FROM message` (e.g. DataGrip) silently misses.

---

## Table of contents

1. [Why this exists](#why-this-exists)
2. [Tech stack](#tech-stack)
3. [Installation](#installation)
4. [Permissions: Full Disk Access](#permissions-full-disk-access)
5. [CLI usage](#cli-usage)
6. [Library usage](#library-usage)
7. [Contact name resolution](#contact-name-resolution)
8. [Data model reference](#data-model-reference)
9. [Architecture](#architecture)
10. [How attributedBody decoding works](#how-attributedbody-decoding-works)
11. [How edits and unsends are stored](#how-edits-and-unsends-are-stored)
12. [Tapback (reaction) codes](#tapback-reaction-codes)
13. [Performance](#performance)
14. [Testing](#testing)
15. [Known limitations](#known-limitations)
16. [References](#references)

---

## Why this exists

Apple's Messages.app stores its data in a single SQLite file at `~/Library/Messages/chat.db`. From macOS Ventura onward, the message body is **no longer stored as plain text** in the `text` column — it's serialized as an `NSAttributedString` and written to the `attributedBody` BLOB column using Apple's legacy NeXT-era `typedstream` archive format.

The practical consequence: opening `chat.db` in DataGrip / TablePlus / `sqlite3` and running `SELECT text FROM message` returns a sea of `NULL`s.

On a representative DB:

| Metric                                           | Count   |
|--------------------------------------------------|---------|
| Total messages                                   | 803,941 |
| `text` column populated                          | 81,053  |
| `attributedBody` populated                       | 800,622 |
| **Invisible to naive SQL** (need decoder)        | **719,569** |

This library decodes `attributedBody` using `pytypedstream` (a pure-Python parser of Apple's typedstream format) with a byte-scan fallback for malformed rows. It also parses `message_summary_info` (binary plist) for edit/unsend history, folds tapback rows into their target message's `reactions` tuple, and exposes everything as immutable Pydantic v2 models.

---

## Tech stack

| Layer | Technology | Why |
|---|---|---|
| Runtime | Python 3.12+ | Modern type syntax (`X \| Y`, `list[X]`, `StrEnum`) |
| Validation / serde | Pydantic v2 | Frozen, strongly-typed models with `model_dump_json()` |
| `attributedBody` decode | [`pytypedstream`](https://pypi.org/project/pytypedstream/) (dgelessus) | Pure-Python decoder for Apple's NeXT typedstream archive format |
| `message_summary_info` decode | stdlib `plistlib` | Apple stores edit history as a binary plist |
| Contacts | macOS AddressBook (`~/Library/Application Support/AddressBook`) via stdlib `sqlite3` | Phone/email → contact name lookup; aggregates across all Sources (Local, iCloud, Google, …) |
| DB | stdlib `sqlite3` (read-only URI) | `chat.db` is SQLite; opened with `file:...?mode=ro&immutable=1` |
| WAL handling | `PRAGMA wal_checkpoint(TRUNCATE)` | Messages.app is usually running; the active WAL must be folded into the main DB before reading |
| CLI | stdlib `argparse` | No extra deps |
| Tests | `pytest` | 67 tests covering decoder, models, time conversion, contacts, and end-to-end on a hand-crafted SQLite |

Dependencies are intentionally minimal — `pydantic` and `pytypedstream` only.

---

## Installation

```bash
pip install -e .          # core
pip install -e '.[dev]'   # core + pytest, mypy, ruff
```

Or directly:

```bash
pip install pydantic pytypedstream
```

---

## Permissions: Full Disk Access

macOS sandboxes `~/Library/Messages/` (and `~/Library/Application Support/AddressBook/`, used for `--names`). The binary that runs your Python code (Terminal.app, iTerm, your IDE, `python` itself if launched as a service) needs **Full Disk Access**:

1. **System Settings** → **Privacy & Security** → **Full Disk Access**.
2. Click `+`, navigate to `/Applications/` (or `/usr/bin/`) and add your terminal or Python interpreter.
3. Restart the terminal.

If you forget, you'll see:

```
imsg.db.FullDiskAccessRequired: Permission denied reading ~/Library/Messages. macOS requires
Full Disk Access for the binary running this code…
```

The library tries to give you a clean error message rather than a raw `PermissionError`.

---

## CLI usage

The CLI snapshots `chat.db` to `/tmp/imsg/` (configurable), runs `PRAGMA wal_checkpoint` on the copy so you don't miss any in-flight messages, then opens the snapshot read-only.

### List chats

```bash
python -m imsg chats
```

Output (truncated):

```
   393  direct   iMessage   iMessage;-;+15555550100  +15555550100
   934  direct   SMS        SMS;-;+15555550101        +15555550101
   422  group    iMessage   chat678123…              Squad Chat
```

Columns: `chat ROWID  |  style  |  service  |  chat GUID  |  identifier or display name`.

### List contacts (handles)

```bash
python -m imsg contacts
```

### Pretty-print messages

```bash
# 50 most recent messages in a specific chat
python -m imsg query --chat 'iMessage;-;+15555550100' -n 50

# 1:1 chat by phone number
python -m imsg query --contact '+15555550100' -n 50

# All of today across every chat
python -m imsg query --since 2026-05-23

# Date range
python -m imsg query --since 2024-01-01 --until 2024-02-01
```

Each line shows: `[timestamp] sender: text` plus markers `[+N att]`, `[N rx]`, `[edited]`, `[unsent]`, `(url)`.

### Dump as JSONL

```bash
# Everything (one Message per line)
python -m imsg dump --out messages.jsonl

# A single chat, last 30 days
python -m imsg dump --chat 'iMessage;-;+15555550100' --since 2026-04-23 --out chat.jsonl

# Pipe directly into jq / sqlite / DuckDB
python -m imsg dump | duckdb -c "SELECT count(*) FROM read_json_auto('/dev/stdin')"
```

### Common flags

| Flag | Default | Description |
|---|---|---|
| `--src DIR` | `~/Library/Messages` | Source dir |
| `--workdir DIR` | `/tmp/imsg` | Where the snapshot is copied |
| `--no-copy` | off | Open the live `chat.db` directly (risky — only safe when Messages.app is quit) |
| `--names` | off | Resolve phone/email handles to contact names via macOS AddressBook (see [Contact name resolution](#contact-name-resolution)) |
| `--chat GUID` | none | Filter to one chat by `chat.guid` |
| `--contact ID` | none | Filter to chat whose `chat_identifier` equals this string (case-insensitive) |
| `--since DATE` / `--until DATE` | none | `YYYY-MM-DD` or ISO datetime (UTC) |
| `--group-events` | off | Include join/leave/title-change rows |
| `-n N` / `--limit N` | unlimited | Cap result count |

With `--names`:

```
[2026-05-22 19:34] Alex Smith: sounds good
[2026-05-22 19:36] Jordan Lee: see you then
```

Without `--names`:

```
[2026-05-22 19:34] +15555550100: sounds good
[2026-05-22 19:36] +15555550101: see you then
```

---

## Library usage

### Quickstart

```python
from imsg import MessageStore, safe_copy_chatdb

snapshot = safe_copy_chatdb()                 # ~/Library/Messages → /tmp/imsg, WAL-checkpointed
with MessageStore(snapshot) as store:
    for chat in store.chats():
        print(chat.identifier, len(chat.participants))

    for m in store.messages(chat_identifier="+15555550100"):
        print(m.sent_at, "me" if m.is_from_me else m.sender, m.text)
```

With contact names:

```python
from imsg import MessageStore, safe_copy_chatdb
from imsg.contacts import ContactBook

contacts = ContactBook.from_default_sources()
with MessageStore(safe_copy_chatdb(), contacts=contacts) as store:
    for m in store.messages(chat_identifier="+15555550100"):
        who = "me" if m.is_from_me else (m.sender_name or m.sender or "?")
        print(m.sent_at, who, m.text)
```

### Filtering

```python
from datetime import datetime, timezone

for m in store.messages(
    chat_guid="iMessage;-;+15555550100",
    since=datetime(2026, 1, 1, tzinfo=timezone.utc),
    until=datetime(2026, 2, 1, tzinfo=timezone.utc),
):
    ...
```

`messages()` is a **generator** — it streams through the DB without loading 800k rows into memory.

### Working with reactions

Tapbacks (👍 ❤️ 😂 etc.) are folded onto their target message's `reactions` tuple. You never see them as standalone messages unless you query the underlying DB directly.

```python
m = store.message_by_guid("4DEA2F9A-A852-4D68-ADA0-636845F85989")
for r in m.reactions:
    print(r.sent_at, r.type.name, "removed" if r.is_removal else "added",
          "by", r.from_handle or "me")
```

### Working with edits and unsends

```python
for m in store.messages():
    if m.edit_history:
        print(f"{m.guid} edited {len(m.edit_history)} time(s):")
        for entry in m.edit_history:
            print(f"  {entry.edited_at}: {entry.text!r}")
    if m.retracted_at:
        print(f"{m.guid} unsent at {m.retracted_at}, parts {m.retracted_parts}")
```

The last entry in `edit_history` is the current text (matches `m.text`); earlier entries are prior versions.

### Working with attachments

```python
for m in store.messages():
    for att in m.attachments:
        print(att.filename, att.mime_type, att.total_bytes, "sticker" if att.is_sticker else "")
```

`att.filename` is the on-disk path inside `~/Library/Messages/Attachments/` (relative paths are expanded by Messages.app — you may need to resolve `~` yourself).

### Serializing to JSON

Every model is Pydantic v2 with `frozen=True`:

```python
for m in store.messages(chat_identifier="+15555550100"):
    print(m.model_dump_json())     # one JSON object per message
```

---

## Contact name resolution

macOS stores contacts in `~/Library/Application Support/AddressBook/` as SQLite databases. There's a top-level aggregator (`AddressBook-v22.abcddb`) plus one DB per account source (Local, iCloud, Google, Exchange, …) under `Sources/<uuid>/AddressBook-v22.abcddb`. `imsg.contacts.ContactBook` snapshots every source DB (with the same WAL-safe pattern as `chat.db`) and aggregates them into a phone-and-email lookup.

### Quickstart

```python
from imsg.contacts import ContactBook

contacts = ContactBook.from_default_sources()
print(contacts.size)                          # total handle→name entries
print(contacts.lookup("+15555550199"))        # "Alex Smith"
print(contacts.lookup("9294126992"))          # same — 10-digit US fallback
print(contacts.lookup("Foo@Example.COM"))     # case-insensitive email match
```

### How the aggregation works

For each `Sources/<uuid>/AddressBook-v22.abcddb`:

1. `shutil.copy2` the DB plus its `-wal` and `-shm` sidecars to `/tmp/imsg/ab/<uuid>/`.
2. `PRAGMA wal_checkpoint(TRUNCATE)` on the copy so pending writes (new contacts not yet checkpointed) are included.
3. Read two queries:
   - `ZABCDPHONENUMBER` join `ZABCDRECORD` → `(first, last, nickname, organization, phone)`.
   - `ZABCDEMAILADDRESS` join `ZABCDRECORD` → `(first, last, nickname, organization, email)`.
4. Build a display name: `nickname` if present, else `first last`, else `organization`.
5. Phone normalization: strip everything except digits and `+`, prepend `+` if missing. Bare 10-digit US numbers get a `+1` fallback at lookup time.
6. Email normalization: trim + lowercase.
7. Aggregate into shared `phones: dict[str, str]` and `emails: dict[str, str]` maps. First source to define a handle wins (later sources don't overwrite).

### Integration with `MessageStore`

When you pass a `ContactBook` to `MessageStore`, each emitted `Message` and `Reaction` gets a resolved `sender_name` / `from_handle_name`. These are `None` when the handle isn't in the address book or when the message is from-me.

```python
m = next(store.messages(chat_identifier="+15555550199"))
print(m.sender, m.sender_name)
# +15555550199  Alex Smith
```

The raw handle is still in `sender` — the name is purely additive, so JSONL dumps remain useful even if the contact db changes later.

### What ends up in `Message.sender_name`?

| Source `chat.db` field | `sender` | `sender_name` (with `--names`) |
|---|---|---|
| iMessage sent by me | `None` | `None` |
| iMessage received from a saved contact | `+15555550199` | `Alex Smith` |
| iMessage received from an unsaved number | `+15551234567` | `None` |
| iMessage received from an email | `foo@example.com` | `Foo Bar` (if saved) |

### Limitations

- We don't watch the AddressBook DB for changes; you'd need to re-construct `ContactBook` to pick up new contacts added since the snapshot.
- Contacts without a name (only an organization) fall through to the org name.
- Group chats: each message still resolves only its individual sender; the group chat itself doesn't get renamed (it uses `display_name` from the `chat` table if Apple set one).

---

## Data model reference

All models live in `imsg.models`. They are immutable (`frozen=True`).

### `Service` (StrEnum)
`IMESSAGE`, `SMS`, `RCS`, `UNKNOWN`.

### `TapbackType` (IntEnum)
`LOVED=2000, LIKED=2001, DISLIKED=2002, LAUGHED=2003, EMPHASIZED=2004, QUESTIONED=2005, STICKER=2006`. Helper: `TapbackType.from_raw(raw_int)` handles both add (2000–2006) and remove (3000–3006) variants.

### `GroupEvent` (IntEnum)
`NONE=0, PARTICIPANT_CHANGE=1, NAME_CHANGE=2, LEAVE=3, IMAGE_CHANGE=4, SHARE_LOCATION=5, STOP_SHARE_LOCATION=6`.

### `Handle`
- `rowid: int` — primary key in `handle` table
- `contact_id: str` — phone (E.164) or email
- `country: str | None`
- `service: Service`

### `Chat`
- `rowid: int`, `guid: str`, `identifier: str`, `display_name: str | None`
- `style: Literal["group", "direct", "unknown"]`
- `service: Service`
- `participants: tuple[str, ...]` — sorted, deduped contact ids

### `Attachment`
- `rowid: int`, `guid: str`, `filename: str | None`, `mime_type: str | None`
- `total_bytes: int | None` (None when DB stores -1 = unknown)
- `is_sticker: bool`, `transfer_name: str | None`

### `Reaction`
- `type: TapbackType`, `is_removal: bool`
- `from_handle: str | None` (None when from-me)
- `from_handle_name: str | None` (populated when `MessageStore` is built with a `ContactBook`)
- `target_guid: str`, `target_part: int | None`
- `sent_at: datetime`, `emoji: str | None` (custom-sticker tapbacks)

### `EditEntry`
- `text: str`, `edited_at: datetime | None`

### `AppPayload`
- `bundle_id: str`, `url: str | None`, `title: str | None`, `summary: str | None`
- Currently populated for `com.apple.messages.URLBalloonProvider` (URL previews); other balloon types record `bundle_id` only.

### `Message`
Every important column from the `message` table, decoded:

- **Identity**: `rowid, guid, chat_guid`
- **Direction**: `sender: str | None` (None ⇒ from-me), `sender_name: str | None` (populated when `MessageStore` is built with a `ContactBook`), `is_from_me: bool`, `service: Service`
- **Timestamps**: `sent_at, delivered_at, read_at` (all `datetime | None`, aware UTC)
- **Body**: `text: str`, `decoded_from_attributed_body: bool`
- **Attachments**: `attachments: tuple[Attachment, ...]`
- **Reactions**: `reactions: tuple[Reaction, ...]` — chronological
- **Threading**: `reply_to_guid, thread_originator_guid, thread_originator_part`
- **Edits**: `edit_history: tuple[EditEntry, ...]`, `retracted_at, retracted_parts`
- **App balloons**: `app_payload: AppPayload | None`
- **Group**: `group_event: GroupEvent, group_title: str | None, item_type: int`

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  ~/Library/Messages/{chat.db, chat.db-wal, chat.db-shm}          │
└────────────────────────────────┬─────────────────────────────────┘
                                 │ shutil.copy2 (FDA required)
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│  /tmp/imsg/{chat.db, chat.db-wal, chat.db-shm}                   │
│  ─ PRAGMA wal_checkpoint(TRUNCATE) on the COPY  ─                │
└────────────────────────────────┬─────────────────────────────────┘
                                 │ file:...?mode=ro&immutable=1
                                 ▼
                       ┌──────────────────────┐
                       │      db.py           │  raw SQL, snapshot
                       └──────────┬───────────┘
                                  │ sqlite3.Row stream
                                  ▼
                       ┌──────────────────────┐
                       │     queries.py       │  MessageStore
                       │   ┌──────────────┐   │   - chats(), contacts()
                       │   │  decoder.py  │   │   - messages() generator
                       │   └──────────────┘   │   - fold tapbacks
                       └──────────┬───────────┘   - decode edits
                                  │ Message
                                  ▼
                       ┌──────────────────────┐
                       │     models.py        │  Pydantic v2 (frozen)
                       └──────────┬───────────┘
                                  │
                ┌─────────────────┴────────────────┐
                ▼                                  ▼
       cli.py (argparse)                Your code / Jupyter
       chats / contacts / dump          import imsg
       query → stdout                   for m in store.messages(): …
```

### File-by-file

| Path | Purpose |
|---|---|
| `imsg/__init__.py` | Public surface re-exports |
| `imsg/constants.py` | `APPLE_EPOCH`, tapback ranges, `GroupEvent`, `is_tapback_type()` |
| `imsg/time_utils.py` | `apple_to_dt()` (handles int ns, int seconds, float seconds) and `dt_to_apple_ns()` |
| `imsg/decoder.py` | `decode_attributed_body()`, `decode_edit_summary()`, `decode_balloon_payload()`, `_byte_scan_nsstring()` |
| `imsg/models.py` | All Pydantic v2 models |
| `imsg/db.py` | `safe_copy_chatdb()`, `connect_readonly()`, `MESSAGE_SQL`, `ATTACHMENT_SQL_TEMPLATE` |
| `imsg/contacts.py` | `ContactBook.from_default_sources()` — phone/email → contact name from AddressBook |
| `imsg/queries.py` | `MessageStore` high-level API |
| `imsg/cli.py` | `argparse` CLI |
| `imsg/__main__.py` | `python -m imsg ...` entry |
| `tests/` | 52 tests across decoder / models / time / e2e |

---

## How attributedBody decoding works

`attributedBody` is an archived `NSMutableAttributedString` in Apple's NeXT-era **typedstream** format (NOT the newer `NSKeyedArchiver` binary plist). Format details:

- Little-endian.
- Starts with `b"\x04\x0bstreamtyped"` magic.
- Sentinels `0x81-0x86` for type prefixes, end-of-object, etc.
- Class chain follows: `NSMutableAttributedString → NSAttributedString → NSObject`.
- First `TypedValue` after the chain (encoding `@` = object) wraps the underlying `NSMutableString`, whose `.value` is the actual text.

Our decoder (`imsg/decoder.py`):

```python
def decode_attributed_body(blob: bytes | None) -> tuple[str, bool]:
    if not blob:
        return "", False
    try:
        obj = typedstream.unarchive_from_data(blob)
        for item in getattr(obj, "contents", []):
            if getattr(item, "encoding", None) == b"@":
                value = getattr(item, "value", None)
                inner = getattr(value, "value", None)
                if isinstance(inner, str):
                    return inner, True
    except Exception:
        pass
    return _byte_scan_nsstring(blob), False
```

**Fallback**: when `pytypedstream` fails (malformed row, future format change), we fall back to a byte scan — find the literal `b"NSString"` marker, skip its 5-byte preamble (`\x01\x94\x84\x01+`), and read a length-prefixed UTF-8 string. If the length byte is `0x81`, read the next 2 bytes as a little-endian u16 length (for strings ≥ 128 chars).

In practice, on a real 800k-message DB, **100% of recent messages decode via `pytypedstream`** — the byte-scan path is rarely exercised. It's there as insurance.

---

## How edits and unsends are stored

iOS 16+ / macOS Ventura+ allow editing and unsending messages within 15 minutes / 2 minutes respectively. Apple chose to **mutate the original row** rather than insert new ones:

- `text` is set to `NULL`.
- `date_edited` / `date_retracted` (Apple ns since 2001) are set.
- `attributedBody` is updated to the current text.
- The full history is stored in `message_summary_info` as a **binary plist** (NOT typedstream) with this shape:

```python
{
    "ec": {                                # "edit content"
        0: [                               # part index (most messages have 1 part = index 0)
            {"t": <typedstream blob>, "d": <float seconds since 2001>},   # original
            {"t": <typedstream blob>, "d": <float seconds since 2001>},   # edit 1
            ...                                                            # current = last
        ],
    },
    "rp": [0, 1, ...],                     # "retracted parts" — part indexes that were unsent
    "otr": {...},                          # per-part metadata
}
```

**Subtle gotcha** caught during testing: the `d` field is a **float in seconds**, not an int in nanoseconds. `apple_to_dt()` auto-detects which unit was given (`isinstance(raw, float) or raw < 10**11` → seconds; else nanoseconds).

---

## Tapback (reaction) codes

The `message` table stores tapbacks as their own rows. They're identified by:

- `associated_message_type != 0`
- `associated_message_guid` = `p:N/<target-guid>` (where `N` is the part index of the target's text) or just `<target-guid>`.

Codes:

| `associated_message_type` | Meaning              | Removal |
|--:|----------------------|--:|
| 2000 | Loved (❤️)            | 3000 |
| 2001 | Liked (👍)            | 3001 |
| 2002 | Disliked (👎)         | 3002 |
| 2003 | Laughed (😂)          | 3003 |
| 2004 | Emphasized (‼️)       | 3004 |
| 2005 | Questioned (❓)        | 3005 |
| 2006 | Sticker / custom (iOS 17+) | 3006 |

`MessageStore.messages()` runs a separate pass to collect every tapback in the requested scope, then attaches them to their target message's `Reaction` tuple sorted by `sent_at`. You never see tapbacks as standalone rows in `messages()` output.

---

## Performance

Measured on a representative DB (803,941 messages, 1.0 GB):

| Operation | Time |
|---|---|
| `safe_copy_chatdb()` (copy + WAL checkpoint) | ~3 s |
| `MessageStore(path)` (loads chat/handle caches) | <1 s |
| `messages(since=2026-05-01)` → 10,898 messages | 1.0 s (~11k msg/s) |
| Full dump (800k messages) | ~75 s |

The bottleneck is `pytypedstream` parsing. If you only need text without styling, the byte-scan fallback is ~5× faster — but the full path is fast enough that we don't expose a "fast mode" toggle.

`messages()` is a generator and streams row-by-row. Memory stays flat regardless of DB size.

---

## Testing

```bash
pytest tests/ -v
```

The suite has **67 tests** across:

- `test_time.py` — `apple_to_dt` covers int ns, int seconds (legacy), float seconds (edit summary); round-trip via `dt_to_apple_ns`.
- `test_constants.py` — `is_tapback_type` and `TapbackType.from_raw` for every code 2000–2006 / 3000–3006 plus negatives.
- `test_decoder.py` — real `attributedBody` fixture decodes to known text via `pytypedstream`; hand-crafted byte-scan inputs; falls back on malformed pytypedstream input; real `message_summary_info` fixture parses; `None`/`b""` / non-plist gracefully return empty.
- `test_models.py` — `Message` is frozen (mutation raises `ValidationError`); `model_dump_json()` round-trips with nested attachments and reactions; `Chat.style` literal is enforced.
- `test_contacts.py` — phone normalization (E.164, parens, dashes, empty), email lowercase/trim, name-building priority (nickname > full > org), lookup with E.164 + 10-digit fallback, missing AddressBook root returns empty book.
- `test_e2e.py` — builds a temp SQLite with the minimal `chat.db` schema, inserts a real `attributedBody` blob + a tapback + an attachment + a group-event row, then opens via `MessageStore` and asserts the resulting `Message` has decoded text, attachments wired, reactions folded, and group events filtered by default.

Fixtures in `tests/fixtures/` are synthetic blobs that exercise the decoder paths without containing any real message data.

---

## Known limitations

- **Read-only**: this library never modifies `chat.db`. It cannot send messages.
- **Attachment bytes**: we record the path and metadata of attachments but never copy/extract the file. Use the path under `~/Library/Messages/Attachments/` directly if you need the binary.
- **Stickers / Genmoji**: recorded as `is_sticker=True` with a `transfer_name`; we don't decode their image data.
- **iCloud sync gap**: `chat.db` is local. If a message lives only on another device and hasn't synced to this Mac yet, we can't see it.
- **`pytypedstream` last released June 2023**: the typedstream format itself hasn't changed since the 1990s, but iOS 18 / macOS 26 occasionally introduce new attribute classes. The byte-scan fallback covers anything `pytypedstream` chokes on.
- **`message_summary_info` schema drift**: we decode defensively (`.get(...)` everywhere) so unknown keys are ignored, not fatal.
- **Disk space**: `safe_copy_chatdb()` duplicates the full `chat.db` into `/tmp/imsg/`. On a 1 GB DB, plan for 1 GB of free temp space. Pass `--workdir` (CLI) or `dst_dir=` (library) to override.

---

## References

- LangChain `iMessage` chat loader — source of the byte-scan fallback algorithm (removed from LangChain as of 0.3; no stable URL).
  https://github.com/langchain-ai/langchain/blob/33875fde2acf6ffb717915a895638274a6098ec2/libs/langchain/langchain_classic/chat_loaders/imessage.py
- Chris Sardegna — "Reverse Engineering Apple's typedstream Format".
  https://chrissardegna.com/blog/reverse-engineering-apples-typedstream-format/
- `dgelessus/python-typedstream` (the `pytypedstream` package).
  https://github.com/dgelessus/python-typedstream
- `ReagentX/imessage-exporter` (Rust crate, reference for `message_summary_info` keys and tapback codes).
  https://github.com/ReagentX/imessage-exporter
- `johnlarkin1/imessage-schema` — full annotated `chat.db` schema dump.
  https://github.com/johnlarkin1/imessage-schema
- Steven Morse — "Analyzing iMessage conversations".
  https://stmorse.github.io/journal/iMessage.html
- Cocoa Core Data timestamp converter (the `978307200` offset).
  https://www.epochconverter.com/coredata
