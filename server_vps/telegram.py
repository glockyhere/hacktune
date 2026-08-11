"""
Telegram bot via long-polling (no webhook/public URL needed for the bot).
Sends each new activation request to your chat with Approve/Reject buttons and
applies your tap to the Store.
"""
from __future__ import annotations
import asyncio
import httpx

from store import Store


class Bot:
    def __init__(self, token: str, chat_id: str, store: Store):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)
        self.store = store
        self._offset = 0

    async def notify_new(self, rec: dict) -> None:
        text = (f"🆕 *Activation request*\n"
                f"code: *{rec['code']}*\n"
                f"VIN: `{rec['vin']}`\n"
                f"car: {rec['make']} {rec['model']}\n"
                f"machine: `{rec['mid']}`")
        markup = {"inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"approve:{rec['rid']}"},
            {"text": "❌ Reject", "callback_data": f"reject:{rec['rid']}"},
        ]]}
        async with httpx.AsyncClient(timeout=20) as c:
            await c.post(self.base + "/sendMessage", json={
                "chat_id": self.chat_id, "text": text,
                "parse_mode": "Markdown", "reply_markup": markup})

    async def _handle_callback(self, cq: dict) -> None:
        if str(cq.get("message", {}).get("chat", {}).get("id")) != self.chat_id:
            return  # ignore anyone who isn't you
        action, _, rid = (cq.get("data") or "").partition(":")
        done = "ignored"
        if action == "approve":
            done = "approved ✅" if self.store.approve(rid) else "not found"
        elif action == "reject":
            done = "rejected ❌" if self.store.reject(rid) else "not found"
        async with httpx.AsyncClient(timeout=20) as c:
            await c.post(self.base + "/answerCallbackQuery",
                         json={"callback_query_id": cq["id"], "text": done})
            # edit the original message so the buttons don't linger
            msg = cq.get("message", {})
            if msg:
                await c.post(self.base + "/editMessageText", json={
                    "chat_id": self.chat_id, "message_id": msg["message_id"],
                    "text": (msg.get("text", "") + f"\n→ {done}"),
                    "parse_mode": "Markdown"})

    async def poll_loop(self) -> None:
        async with httpx.AsyncClient(timeout=40) as c:
            while True:
                try:
                    r = await c.get(self.base + "/getUpdates",
                                    params={"timeout": 30, "offset": self._offset})
                    for upd in r.json().get("result", []):
                        self._offset = upd["update_id"] + 1
                        if "callback_query" in upd:
                            await self._handle_callback(upd["callback_query"])
                except Exception:
                    await asyncio.sleep(3)
