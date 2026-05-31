"""Map iMessage handle ids (phone numbers / emails) to contact names.

Reads macOS AddressBook databases at ~/Library/Application Support/AddressBook/Sources/<uuid>/
AddressBook-v22.abcddb. The top-level AddressBook-v22.abcddb is just an aggregator; the per-source
DBs (Local, iCloud, Google, etc.) hold the actual records.
"""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
from pathlib import Path

DEFAULT_AB_ROOT: Path = Path.home() / "Library" / "Application Support" / "AddressBook"
DEFAULT_AB_WORKDIR: Path = Path("/tmp/imsg/ab")

_DIGITS_RE = re.compile(r"[^\d+]")

log = logging.getLogger(__name__)


def _normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    cleaned = _DIGITS_RE.sub("", raw)
    if not cleaned:
        return ""
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


def _normalize_email(raw: str) -> str:
    return raw.strip().lower()


def _build_name(first: str | None, last: str | None, nickname: str | None, org: str | None) -> str | None:
    parts: list[str] = []
    if nickname:
        return nickname.strip()
    if first:
        parts.append(first.strip())
    if last:
        parts.append(last.strip())
    if parts:
        return " ".join(parts)
    if org:
        return org.strip()
    return None


class ContactBook:
    def __init__(self, phones: dict[str, str], emails: dict[str, str]) -> None:
        self._phones = phones
        self._emails = emails

    @property
    def size(self) -> int:
        return len(self._phones) + len(self._emails)

    def lookup(self, handle_id: str) -> str | None:
        if not handle_id:
            return None
        if "@" in handle_id:
            return self._emails.get(_normalize_email(handle_id))
        norm = _normalize_phone(handle_id)
        if norm in self._phones:
            return self._phones[norm]
        # Fall back: bare 10-digit US number -> try with +1
        digits = norm.lstrip("+")
        if digits.isdigit() and len(digits) == 10:
            return self._phones.get("+1" + digits)
        return None

    @classmethod
    def from_default_sources(
        cls,
        src_root: Path = DEFAULT_AB_ROOT,
        dst_root: Path = DEFAULT_AB_WORKDIR,
    ) -> "ContactBook":
        if not src_root.exists():
            log.info("AddressBook root not found at %s; ContactBook will be empty", src_root)
            return cls({}, {})
        dst_root.mkdir(parents=True, exist_ok=True)

        phones: dict[str, str] = {}
        emails: dict[str, str] = {}
        sources_dir = src_root / "Sources"
        if not sources_dir.exists():
            return cls({}, {})

        for src_db in sorted(sources_dir.glob("*/AddressBook-v22.abcddb")):
            uuid = src_db.parent.name
            dst_dir = dst_root / uuid
            try:
                dst_dir.mkdir(exist_ok=True)
                for name in (
                    "AddressBook-v22.abcddb",
                    "AddressBook-v22.abcddb-wal",
                    "AddressBook-v22.abcddb-shm",
                ):
                    s = src_db.parent / name
                    if s.exists():
                        shutil.copy2(s, dst_dir / name)
            except PermissionError as exc:
                log.warning("skipping AddressBook source %s: %s", uuid, exc)
                continue
            dst = dst_dir / "AddressBook-v22.abcddb"
            try:
                conn = sqlite3.connect(str(dst))
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                conn.commit()
                conn.close()
            except sqlite3.Error as exc:
                log.debug("WAL checkpoint failed for %s: %s", uuid, exc)

            cls._load_one(dst, phones, emails)

        return cls(phones, emails)

    @staticmethod
    def _load_one(db: Path, phones: dict[str, str], emails: dict[str, str]) -> None:
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        except sqlite3.Error as exc:
            log.debug("cannot open %s: %s", db, exc)
            return
        con.row_factory = sqlite3.Row
        try:
            phone_rows = con.execute(
                """SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZNICKNAME, r.ZORGANIZATION, p.ZFULLNUMBER
                   FROM   ZABCDPHONENUMBER p
                   JOIN   ZABCDRECORD r ON r.Z_PK = p.ZOWNER
                   WHERE  p.ZFULLNUMBER IS NOT NULL"""
            ).fetchall()
            for r in phone_rows:
                name = _build_name(r["ZFIRSTNAME"], r["ZLASTNAME"], r["ZNICKNAME"], r["ZORGANIZATION"])
                if not name:
                    continue
                norm = _normalize_phone(r["ZFULLNUMBER"])
                if norm and norm not in phones:
                    phones[norm] = name
        except sqlite3.Error as exc:
            log.debug("phone query failed on %s: %s", db, exc)

        try:
            email_rows = con.execute(
                """SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZNICKNAME, r.ZORGANIZATION, e.ZADDRESS
                   FROM   ZABCDEMAILADDRESS e
                   JOIN   ZABCDRECORD r ON r.Z_PK = e.ZOWNER
                   WHERE  e.ZADDRESS IS NOT NULL"""
            ).fetchall()
            for r in email_rows:
                name = _build_name(r["ZFIRSTNAME"], r["ZLASTNAME"], r["ZNICKNAME"], r["ZORGANIZATION"])
                if not name:
                    continue
                norm = _normalize_email(r["ZADDRESS"])
                if norm and norm not in emails:
                    emails[norm] = name
        except sqlite3.Error as exc:
            log.debug("email query failed on %s: %s", db, exc)
        finally:
            con.close()
