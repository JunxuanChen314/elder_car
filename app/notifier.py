"""Telegram Bot and Twilio SMS alerts with per-key cooldowns to prevent repeated notifications."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

_last_sent: dict[str, float] = {}
_lock = threading.Lock()


def _send_telegram(bot_token: str, chat_id: str, text: str) -> tuple[bool, str]:
    token = (bot_token or "").strip()
    cid = (chat_id or "").strip()
    if not token or not cid:
        return False, "Bot token or chat ID is not configured"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": cid,
                "text": text[:4096],
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("ok"):
                return True, "Telegram accepted the message"
            return False, str(data.get("description", r.text))[:180]
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        log.exception("Telegram delivery error")
        return False, str(e)[:180]


def _send_twilio_sms(
    body: str,
    *,
    account_sid: str,
    auth_token: str,
    from_number: str,
    to_e164: str,
) -> tuple[bool, str]:
    if not account_sid or not auth_token or not from_number or not to_e164:
        return False, "Twilio configuration is incomplete"
    try:
        from twilio.rest import Client

        client = Client(account_sid, auth_token)
        msg = client.messages.create(
            body=body[:1400],
            from_=from_number,
            to=to_e164,
        )
        return True, f"Sent; sid={getattr(msg, 'sid', '')}"
    except Exception as e:
        return False, f"Delivery failed: {e}"


def dispatch_alert(body: str, key: str, cfg: Any) -> list[str]:
    """
    Send alerts through configured Telegram and/or Twilio channels. A key triggers
    only once during SMS_COOLDOWN_SEC. Returns event-log messages.
    """
    body = (body or "").strip()
    if not body:
        return ["Notification body is empty"]

    try:
        cd = int(getattr(cfg, "SMS_COOLDOWN_SEC", 120) or 120)
    except (TypeError, ValueError):
        cd = 120
    cd = max(10, cd)

    with _lock:
        now = time.time()
        prev = _last_sent.get(key, 0.0)
        if now - prev < cd:
            return [f"Notification cooldown active for {key}; skipped"]
        _last_sent[key] = now

    lines: list[str] = []
    tg_tok = (getattr(cfg, "TELEGRAM_BOT_TOKEN", "") or "").strip()
    tg_chat = (getattr(cfg, "TELEGRAM_CHAT_ID", "") or "").strip()
    sid = (getattr(cfg, "TWILIO_ACCOUNT_SID", "") or "").strip()
    tok = (getattr(cfg, "TWILIO_AUTH_TOKEN", "") or "").strip()
    frm = (getattr(cfg, "TWILIO_FROM_NUMBER", "") or "").strip()
    to_e164 = (getattr(cfg, "ALERT_PHONE_E164", "") or "").strip()

    has_channel = False

    if tg_tok and tg_chat:
        has_channel = True
        ok, info = _send_telegram(tg_tok, tg_chat, body)
        if ok:
            lines.append(f"Telegram: delivered · {info}")
        else:
            lines.append(f"Telegram: failed · {info}")

    if sid and tok and frm and to_e164:
        has_channel = True
        ok, info = _send_twilio_sms(
            body,
            account_sid=sid,
            auth_token=tok,
            from_number=frm,
            to_e164=to_e164,
        )
        if ok:
            lines.append(f"SMS: sent (accepted by Twilio) · {info}")
        else:
            lines.append(f"SMS: not sent · {info}")

    if not has_channel:
        lines.append(
            "No notification channel configured. Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID and/or Twilio credentials + ALERT_PHONE_E164."
        )

    return lines


def send_sms(
    body: str,
    *,
    account_sid: str,
    auth_token: str,
    from_number: str,
    to_e164: str,
    cooldown_key: str,
    cooldown_sec: int,
) -> tuple[bool, str]:
    """Backward-compatible SMS-only call that uses the shared cooldown table."""
    body = (body or "").strip()
    to_e164 = (to_e164 or "").strip()
    if not account_sid or not auth_token or not from_number or not to_e164:
        return False, "Twilio or recipient number is not configured; SMS skipped"

    now = time.time()
    with _lock:
        prev = _last_sent.get(cooldown_key, 0.0)
        if now - prev < max(10, cooldown_sec):
            return False, f"Cooldown active for {cooldown_key}; message not sent"
        _last_sent[cooldown_key] = now

    return _send_twilio_sms(
        body,
        account_sid=account_sid,
        auth_token=auth_token,
        from_number=from_number,
        to_e164=to_e164,
    )
