"""Meta Conversions API — server-side Purchase event firing.

Fires non-blocking on subscription_confirmed. Fails silently with Sentry log.
"""
import asyncio
import hashlib
import logging
import time

import httpx

import config

try:
    import sentry_sdk as _sentry
except ImportError:
    _sentry = None  # type: ignore[assignment]

log = logging.getLogger("mzansiedge.meta_capi")

_CAPI_URL = "https://graph.facebook.com/v19.0/{pixel_id}/events"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def _lookup_user_data(user_id: int, db_path: str | None) -> dict:
    from db_connection import get_connection
    try:
        conn = get_connection(db_path, timeout_ms=3000)
        try:
            row = conn.execute(
                """SELECT wc.ctwa_clid, u.email, u.whatsapp_phone, u.fb_click_id
                   FROM users u
                   LEFT JOIN wa_contacts wc ON wc.phone_number = u.whatsapp_phone
                   WHERE u.id = ?
                   LIMIT 1""",
                (user_id,),
            ).fetchone()
        finally:
            conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


async def fire_purchase_event(
    user_id: int,
    amount_cents: int,
    plan_code: str,
    db_path: str | None = None,
) -> None:
    """Fire Meta CAPI Purchase event. Non-blocking, silent failure."""
    pixel_id = getattr(config, "META_PIXEL_ID", None)
    access_token = getattr(config, "META_CAPI_ACCESS_TOKEN", None)
    if not pixel_id or not access_token:
        log.debug("CAPI not configured — skipping")
        return

    resolved_path = db_path or (str(config.DATABASE_PATH) if config.DATABASE_PATH else None)

    try:
        row = await asyncio.to_thread(_lookup_user_data, user_id, resolved_path)

        ctwa_clid = row.get("ctwa_clid") or row.get("fb_click_id")
        phone = row.get("whatsapp_phone")
        email = row.get("email")

        user_data: dict = {}
        if ctwa_clid:
            user_data["ctwa_clid"] = ctwa_clid
        if phone:
            user_data["ph"] = [_sha256(phone)]
        if email:
            user_data["em"] = [_sha256(email)]

        payload = {
            "data": [{
                "event_name": "Purchase",
                "event_time": int(time.time()),
                "action_source": "system_generated",
                "user_data": user_data,
                "custom_data": {
                    "value": round(amount_cents / 100.0, 2),
                    "currency": "ZAR",
                    "content_name": plan_code,
                },
            }]
        }

        url = _CAPI_URL.format(pixel_id=pixel_id)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                params={"access_token": access_token},
                json=payload,
            )
            if resp.status_code == 200:
                log.info(
                    "CAPI Purchase fired: user=%d plan=%s ctwa=%s",
                    user_id, plan_code, bool(ctwa_clid),
                )
            else:
                log.warning(
                    "CAPI Purchase non-200 %d: %s",
                    resp.status_code, resp.text[:200],
                )
    except Exception as exc:
        log.error("CAPI fire_purchase_event failed: %s", exc)
        if _sentry:
            try:
                _sentry.capture_exception(exc)
            except Exception:
                pass
