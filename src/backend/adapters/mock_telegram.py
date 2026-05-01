from __future__ import annotations

from backend.schemas import (
    TelegramMessageReference,
    TelegramPollUpdatesQuery,
    TelegramSendMessagePayload,
    TelegramUpdateEnvelope,
)


class MockTelegram:
    def __init__(self) -> None:
        self.sent_messages: list[TelegramSendMessagePayload] = []
        self._updates: list[TelegramUpdateEnvelope] = []
        self._message_sequence = 0
        self._update_sequence = 0

    def send_message(self, payload: TelegramSendMessagePayload) -> TelegramMessageReference:
        self._message_sequence += 1
        stored_payload = payload.model_copy(deep=True)
        self.sent_messages.append(stored_payload)
        return TelegramMessageReference(
            chat_id=stored_payload.chat_id,
            message_id=self._message_sequence,
            message_thread_id=stored_payload.message_thread_id,
        )

    def poll_updates(self, query: TelegramPollUpdatesQuery) -> list[TelegramUpdateEnvelope]:
        updates = [
            update
            for update in self._updates
            if query.offset is None or update.update_id >= query.offset
        ]
        return [update.model_copy(deep=True) for update in updates[: query.limit]]

    def add_update(
        self,
        *,
        chat_id: str,
        text: str,
        author: str | None = None,
        message_thread_id: int | None = None,
        reply_to_message_id: int | None = None,
    ) -> TelegramUpdateEnvelope:
        self._update_sequence += 1
        self._message_sequence += 1
        update = TelegramUpdateEnvelope(
            update_id=self._update_sequence,
            chat_id=chat_id,
            message_id=self._message_sequence,
            text=text,
            author=author,
            message_thread_id=message_thread_id,
            reply_to_message_id=reply_to_message_id,
        )
        self._updates.append(update)
        return update


__all__ = ["MockTelegram"]
