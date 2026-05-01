from typing import Protocol, runtime_checkable

from backend.schemas import (
    TelegramMessageReference,
    TelegramPollUpdatesQuery,
    TelegramSendMessagePayload,
    TelegramUpdateEnvelope,
)


@runtime_checkable
class TelegramProtocol(Protocol):
    def send_message(self, payload: TelegramSendMessagePayload) -> TelegramMessageReference: ...

    def poll_updates(self, query: TelegramPollUpdatesQuery) -> list[TelegramUpdateEnvelope]: ...


__all__ = ["TelegramProtocol"]
