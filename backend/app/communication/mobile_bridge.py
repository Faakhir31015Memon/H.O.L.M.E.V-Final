"""Communication bridge: send through something real, or say what is missing.

The old version asserted `device_connected = True`, then answered every request with
`SENT`, `CALLING` or `DISPATCHED` and a hardcoded Unsplash picture as "your gallery
photo". None of it touched a phone or a mail server.

What is genuinely possible on this machine today:

* **email** - stdlib SMTP, using credentials the user puts in `.env`. This really sends.
* **WhatsApp / dialling / gallery** - only through a companion bridge running on the
  phone (Tasker, Termux, or the H.O.L.M.E.V agent). Without `MOBILE_BRIDGE_URL` these
  refuse and name the missing piece; there is no free "send WhatsApp" API to call.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Any

import httpx

from app.config.settings import settings

logger = logging.getLogger("holmev.mobile_bridge")

EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
BRIDGE_TIMEOUT_S = 15.0


def bridge_url() -> str:
    return (os.environ.get("MOBILE_BRIDGE_URL") or settings.MOBILE_BRIDGE_URL or "").strip().rstrip("/")


class MobileBridgeService:
    """Phone-side actions need the bridge; email needs SMTP. Both say so."""

    @property
    def device_connected(self) -> bool:
        return bool(bridge_url())

    @property
    def device_name(self) -> str:
        return bridge_url() if self.device_connected else "no phone bridge is paired"

    @property
    def email_is_real(self) -> bool:
        return bool(settings.SMTP_HOST and settings.SMTP_FROM_ADDRESS)

    def status(self) -> dict[str, Any]:
        return {
            "phone_bridge": bridge_url() or None,
            "email_transport": settings.SMTP_HOST or None,
            "email_from": settings.SMTP_FROM_ADDRESS or None,
            "email_is_real": self.email_is_real,
        }

    # ------------------------------------------------------------------ phone bridge

    async def _ask_bridge(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{bridge_url()}{path}"
        headers = {"Content-Type": "application/json"}
        if settings.MOBILE_BRIDGE_TOKEN:
            headers["Authorization"] = f"Bearer {settings.MOBILE_BRIDGE_TOKEN}"
        try:
            async with httpx.AsyncClient(timeout=BRIDGE_TIMEOUT_S) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as exc:
            return {"sent": False, "status": "BRIDGE_UNREACHABLE", "reason": f"{url} did not answer: {exc}"[:200]}
        except ValueError:
            return {"sent": False, "status": "BRIDGE_BAD_REPLY", "reason": f"{url} returned a non-JSON reply"}

        reported = str(body.get("status") or "ACCEPTED")
        return {
            "sent": True,
            "status": f"ACCEPTED_BY_BRIDGE ({reported})",
            "delivered": False,
            "bridge_reply": body,
            "note": "the bridge accepted it; delivery needs the bridge's own receipt",
        }

    def _no_bridge(self, action: str) -> dict[str, Any]:
        return {
            "sent": False,
            "delivered": False,
            "status": "NOT_SENT",
            "reason": (
                f"'{action}' needs a phone bridge and none is paired. Run a receiver on the phone "
                "(Tasker/Termux HTTP endpoint or the H.O.L.M.E.V agent) and set MOBILE_BRIDGE_URL "
                "in backend/.env. Until then nothing here can put a message on that handset."
            ),
        }

    async def send_whatsapp_message(self, recipient: str, message_text: str) -> dict[str, Any]:
        if not (recipient or "").strip() or not (message_text or "").strip():
            return {"sent": False, "status": "NOT_SENT", "reason": "a recipient and a message are both required"}
        if not self.device_connected:
            return self._no_bridge("WhatsApp send")
        result = await self._ask_bridge("/whatsapp/send", {"to": recipient, "text": message_text})
        result.update({"recipient": recipient, "timestamp": time.time()})
        return result

    async def make_phone_call(self, contact: str) -> dict[str, Any]:
        if not (contact or "").strip():
            return {"called": False, "status": "NOT_DIALED", "reason": "no contact was named"}
        if not self.device_connected:
            refused = self._no_bridge("dial a call")
            refused["called"] = False
            return refused
        result = await self._ask_bridge("/call/dial", {"contact": contact})
        result["called"] = bool(result.get("sent"))
        result["contact"] = contact
        return result

    async def fetch_mobile_gallery_image(self, query: str = "latest") -> dict[str, Any]:
        if not self.device_connected:
            return {
                "retrieved": False,
                "status": "NOT_RETRIEVED",
                "reason": "the phone gallery is on the handset; pair MOBILE_BRIDGE_URL to read it",
            }
        result = await self._ask_bridge("/gallery/search", {"query": query})
        result["retrieved"] = bool(result.get("sent"))
        return result

    # ------------------------------------------------------------------ email (real)

    async def send_email(self, recipient_email: str, subject: str, body: str) -> dict[str, Any]:
        """Send through SMTP. Blocking socket work stays off the event loop."""

        address = (recipient_email or "").strip()
        if not EMAIL_SHAPE.match(address):
            return {"sent": False, "status": "NOT_SENT", "reason": f"'{recipient_email}' is not an email address"}
        if not self.email_is_real:
            return {
                "sent": False,
                "status": "NOT_SENT",
                "reason": (
                    "no SMTP server is configured. Set SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD "
                    "and SMTP_FROM_ADDRESS in backend/.env (an app password is the usual choice) and email "
                    "sends for real from here."
                ),
            }

        return await asyncio.to_thread(self._smtp_send, address, subject or "(no subject)", body or "")

    def _smtp_send(self, address: str, subject: str, body: str) -> dict[str, Any]:
        message = EmailMessage()
        message["From"] = settings.SMTP_FROM_ADDRESS
        message["To"] = address
        message["Subject"] = subject
        message.set_content(body)

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
                if settings.SMTP_USE_TLS:
                    server.starttls(context=context)
                if settings.SMTP_USERNAME:
                    server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                server.send_message(message)
        except Exception as exc:
            logger.warning("SMTP send failed: %s", type(exc).__name__)
            return {
                "sent": False,
                "status": "NOT_SENT",
                "reason": f"the mail server refused: {type(exc).__name__}: {exc}"[:250],
                "to": address,
            }

        # The server accepted the message for delivery. That is the strongest claim
        # available without a read receipt, and it is what this says.
        return {
            "sent": True,
            "status": "ACCEPTED_BY_SMTP_SERVER",
            "delivered": False,
            "to": address,
            "subject": subject,
            "via": f"{settings.SMTP_HOST}:{settings.SMTP_PORT}",
            "timestamp": time.time(),
        }


mobile_bridge_service = MobileBridgeService()
