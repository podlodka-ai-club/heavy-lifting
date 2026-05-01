from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.schemas import (
    TelegramMessageReference,
    TelegramPollUpdatesQuery,
    TelegramSendMessagePayload,
    TelegramUpdateEnvelope,
)

HttpRequester = Callable[[urllib.request.Request, float], Any]


@dataclass(frozen=True, slots=True)
class TelegramBotConfig:
    token_env_var: str
    timeout_seconds: int = 30
    api_base_url: str = "https://api.telegram.org"


def _default_http_requester(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


class TelegramBotApi:
    def __init__(
        self,
        config: TelegramBotConfig,
        *,
        http_requester: HttpRequester | None = None,
    ) -> None:
        self._config = config
        self._http_requester = http_requester or _default_http_requester

    def send_message(self, payload: TelegramSendMessagePayload) -> TelegramMessageReference:
        variables: dict[str, Any] = {
            "chat_id": payload.chat_id,
            "text": payload.text,
        }
        if payload.message_thread_id is not None:
            variables["message_thread_id"] = payload.message_thread_id
        if payload.reply_to_message_id is not None:
            variables["reply_to_message_id"] = payload.reply_to_message_id

        data = self._execute("sendMessage", variables)
        result = data.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Telegram sendMessage response missing result")
        message_id = result.get("message_id")
        if not isinstance(message_id, int):
            raise RuntimeError("Telegram sendMessage response missing message_id")
        chat_id = _extract_chat_id(result.get("chat")) or payload.chat_id
        thread_id = result.get("message_thread_id")
        return TelegramMessageReference(
            chat_id=chat_id,
            message_id=message_id,
            message_thread_id=thread_id if isinstance(thread_id, int) else None,
        )

    def poll_updates(self, query: TelegramPollUpdatesQuery) -> list[TelegramUpdateEnvelope]:
        variables: dict[str, Any] = {"limit": query.limit}
        if query.offset is not None:
            variables["offset"] = query.offset

        data = self._execute("getUpdates", variables)
        result = data.get("result")
        if not isinstance(result, list):
            raise RuntimeError("Telegram getUpdates response missing result list")

        updates: list[TelegramUpdateEnvelope] = []
        for raw_update in result:
            parsed = _parse_update(raw_update)
            if parsed is not None:
                updates.append(parsed)
        return updates

    def _execute(self, method: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        token = os.getenv(self._config.token_env_var)
        if not token:
            raise RuntimeError(f"Telegram token env var {self._config.token_env_var} is empty")

        body = urllib.parse.urlencode(dict(variables)).encode("utf-8")
        request = urllib.request.Request(
            f"{self._config.api_base_url}/bot{token}/{method}",
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        try:
            response = self._http_requester(request, float(self._config.timeout_seconds))
        except urllib.error.HTTPError as exc:
            response = exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Telegram transport error for {method}: {exc.reason}") from None

        try:
            raw = response.read() or b""
        except Exception:
            raw = b""
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        status_attr = getattr(response, "status", None)
        if not isinstance(status_attr, int):
            status_attr = getattr(response, "code", 200)
        status: int = status_attr if isinstance(status_attr, int) else 200

        try:
            payload: Any = json.loads(raw.decode("utf-8")) if raw else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None

        if status >= 400:
            raise RuntimeError(f"Telegram Bot API HTTP {status} for {method}")
        if not isinstance(payload, dict):
            raise RuntimeError(f"Telegram Bot API invalid JSON for {method}")
        if payload.get("ok") is not True:
            description = payload.get("description")
            suffix = f": {description}" if isinstance(description, str) else ""
            raise RuntimeError(f"Telegram Bot API returned ok=false for {method}{suffix}")
        return payload


def _parse_update(raw_update: Any) -> TelegramUpdateEnvelope | None:
    if not isinstance(raw_update, dict):
        return None
    update_id = raw_update.get("update_id")
    if not isinstance(update_id, int):
        return None
    message = raw_update.get("message")
    if not isinstance(message, dict):
        message = raw_update.get("edited_message")
    if not isinstance(message, dict):
        return None

    message_id = message.get("message_id")
    chat_id = _extract_chat_id(message.get("chat"))
    if not isinstance(message_id, int) or chat_id is None:
        return None

    from_user = message.get("from")
    author = None
    if isinstance(from_user, dict):
        username = from_user.get("username")
        first_name = from_user.get("first_name")
        author = username if isinstance(username, str) else None
        if author is None and isinstance(first_name, str):
            author = first_name

    reply_to = message.get("reply_to_message")
    reply_to_message_id = None
    if isinstance(reply_to, dict) and isinstance(reply_to.get("message_id"), int):
        reply_to_message_id = reply_to["message_id"]

    thread_id = message.get("message_thread_id")
    text = message.get("text")
    return TelegramUpdateEnvelope(
        update_id=update_id,
        chat_id=chat_id,
        message_id=message_id,
        text=text if isinstance(text, str) else None,
        author=author,
        message_thread_id=thread_id if isinstance(thread_id, int) else None,
        reply_to_message_id=reply_to_message_id,
        metadata={"telegram_update_type": "message"},
    )


def _extract_chat_id(raw_chat: Any) -> str | None:
    if not isinstance(raw_chat, dict):
        return None
    chat_id = raw_chat.get("id")
    if isinstance(chat_id, int | str):
        return str(chat_id)
    return None


__all__ = ["HttpRequester", "TelegramBotApi", "TelegramBotConfig"]
