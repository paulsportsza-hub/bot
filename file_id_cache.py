"""BUILD-FILE-ID-REUSE-01: Persistent SQLite-backed Telegram file_id cache.

After a successful send_photo, the Telegram file_id returned is stored here.
On repeat sends with identical content (same cache_key), the file_id is used
directly — no Playwright render, no upload.

TTL: 7 days.  Telegram file_ids are permanent server-side, but we expire
     after 7 days so stale template/data changes never get served from cache.
DB:  data/mzansiedge.db (via config.DATABASE_PATH), table `card_file_ids`.
     Uses get_connection factory (W81-DBLOCK compliant — never bare sqlite3.connect).

Thread-safety: WAL mode + connection-per-call.  Each get/put/invalidate opens
and closes its own connection so there is no shared state between threads.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

_FILE_ID_TTL = 7 * 24 * 3600  # 7 days in seconds


def _get_db_path() -> str:
    """Resolve the bot's main SQLite DB path."""
    try:
        import config as _cfg  # type: ignore[import]
        if _cfg.DATABASE_PATH:
            return str(_cfg.DATABASE_PATH)
    except Exception:
        pass
    return str(Path(__file__).parent / "data" / "mzansiedge.db")


def _ensure_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS card_file_ids (
            cache_key  TEXT PRIMARY KEY,
            file_id    TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_card_file_ids_expires"
        " ON card_file_ids (expires_at)"
    )
    conn.commit()


class FileIdCache:
    """Persistent Telegram file_id store backed by SQLite.

    All operations are best-effort: any DB failure is swallowed so a broken
    cache never interrupts a card send.  Pass db_path to the constructor to
    override the resolved DB location (useful in tests).
    """

    def __init__(
        self,
        default_ttl: int = _FILE_ID_TTL,
        db_path: str | None = None,
    ) -> None:
        self._ttl = default_ttl
        self._db_path = db_path  # None → resolved dynamically via _get_db_path()

    def _conn(self):
        from db_connection import get_connection  # type: ignore[import]
        return get_connection(self._db_path or _get_db_path(), timeout_ms=3000)

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, cache_key: str) -> str | None:
        """Return the stored file_id for cache_key, or None on miss/expiry."""
        try:
            conn = self._conn()
            try:
                _ensure_table(conn)
                row = conn.execute(
                    "SELECT file_id, expires_at FROM card_file_ids WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
                if row is None:
                    return None
                if time.time() > row["expires_at"]:
                    conn.execute(
                        "DELETE FROM card_file_ids WHERE cache_key = ?",
                        (cache_key,),
                    )
                    conn.commit()
                    return None
                return row["file_id"]
            finally:
                conn.close()
        except Exception as exc:
            log.debug("file_id_cache.get(%s) failed: %s", cache_key, exc)
            return None

    def put(self, cache_key: str, file_id: str, ttl: int | None = None) -> None:
        """Store file_id under cache_key with the given TTL (default 7 days)."""
        if not file_id:
            return
        _expires = time.time() + (ttl if ttl is not None else self._ttl)
        try:
            conn = self._conn()
            try:
                _ensure_table(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO card_file_ids"
                    " (cache_key, file_id, expires_at) VALUES (?, ?, ?)",
                    (cache_key, file_id, _expires),
                )
                conn.commit()
                log.debug("file_id_cache.put(%s) stored", cache_key)
            finally:
                conn.close()
        except Exception as exc:
            log.debug("file_id_cache.put(%s) failed: %s", cache_key, exc)

    def invalidate(self, cache_key: str) -> None:
        """Remove cache_key (called when Telegram rejects a stored file_id)."""
        try:
            conn = self._conn()
            try:
                conn.execute(
                    "DELETE FROM card_file_ids WHERE cache_key = ?",
                    (cache_key,),
                )
                conn.commit()
                log.debug("file_id_cache.invalidate(%s)", cache_key)
            finally:
                conn.close()
        except Exception as exc:
            log.debug("file_id_cache.invalidate(%s) failed: %s", cache_key, exc)

    def stats(self) -> dict:
        """Return {entries, expired} counts for monitoring."""
        try:
            conn = self._conn()
            try:
                _ensure_table(conn)
                now = time.time()
                total = conn.execute(
                    "SELECT COUNT(*) FROM card_file_ids"
                ).fetchone()[0]
                expired = conn.execute(
                    "SELECT COUNT(*) FROM card_file_ids WHERE expires_at < ?",
                    (now,),
                ).fetchone()[0]
                return {"entries": total, "expired": expired}
            finally:
                conn.close()
        except Exception as exc:
            log.debug("file_id_cache.stats() failed: %s", exc)
            return {"entries": 0, "expired": 0}

    def clear_all(self) -> int:
        """Delete every row from card_file_ids. Returns rows removed."""
        try:
            conn = self._conn()
            try:
                _ensure_table(conn)
                cur = conn.execute("DELETE FROM card_file_ids")
                conn.commit()
                return cur.rowcount or 0
            finally:
                conn.close()
        except Exception as exc:
            log.warning("file_id_cache.clear_all() failed: %s", exc)
            return 0

    async def startup_token_rotation_probe(self, bot) -> bool:
        """FIX-FILE-ID-REUSE-AC5-AC6-01 (AC5): detect bot-token rotation at startup.

        Picks any one cached row, calls ``bot.get_file(file_id)``. If Telegram
        returns ``Forbidden`` (bot kicked) or ``BadRequest: Wrong file
        identifier`` (file_id is dead — strongest signal that the bot token
        rotated and every cached file_id is now invalid), wipes the entire
        ``card_file_ids`` table so subsequent sends re-render and re-cache
        cleanly. Any other exception is treated as a transient single-file_id
        failure (e.g. natural TTL miss mid-life) and does NOT clear the table.

        Returns True if the table was cleared, False otherwise.
        """
        try:
            conn = self._conn()
            try:
                _ensure_table(conn)
                row = conn.execute(
                    "SELECT cache_key, file_id FROM card_file_ids LIMIT 1"
                ).fetchone()
            finally:
                conn.close()
        except Exception as exc:
            log.debug("startup_token_rotation_probe: DB read failed: %s", exc)
            return False

        if row is None:
            return False

        try:
            from telegram.error import BadRequest, Forbidden
        except Exception:
            BadRequest = Exception  # type: ignore[assignment]
            Forbidden = Exception  # type: ignore[assignment]

        file_id = row["file_id"]
        try:
            await bot.get_file(file_id)
            return False
        except Forbidden as exc:
            log.warning(
                "file_id_cache: token rotation probe got Forbidden (%s) — clearing card_file_ids",
                exc,
            )
            removed = self.clear_all()
            log.warning("file_id_cache: cleared %d rows after token-rotation signal", removed)
            return True
        except BadRequest as exc:
            if "wrong file identifier" in str(exc).lower():
                log.warning(
                    "file_id_cache: probe got 'Wrong file identifier' — clearing card_file_ids",
                )
                removed = self.clear_all()
                log.warning(
                    "file_id_cache: cleared %d rows after token-rotation signal", removed
                )
                return True
            log.debug("startup_token_rotation_probe: BadRequest (not rotation): %s", exc)
            return False
        except Exception as exc:
            log.debug("startup_token_rotation_probe: transient error (no clear): %s", exc)
            return False


# Singleton — imported by card_sender
file_id_cache = FileIdCache()
