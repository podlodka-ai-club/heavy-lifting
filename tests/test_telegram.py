from __future__ import annotations

import json
from io import BytesIO

import pytest

from backend.adapters.mock_telegram import MockTelegram
from backend.adapters.telegram_bot import TelegramBotApi, TelegramBotConfig
from backend.schemas import TelegramPollUpdatesQuery, TelegramSendMessagePayload


class FakeResponse:
    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self._raw = json.dumps(payload).encode("utf-8")
        self.status = status
        self._stream = BytesIO(self._raw)

    def read(self) -> bytes:
        return self._stream.read()

    def close(self) -> None:
        pass


def test_mock_telegram_sends_and_polls_updates_idempotently() -> None:
    telegram = MockTelegram()

    sent = telegram.send_message(
        TelegramSendMessagePayload(chat_id="-1001", text="Question", message_thread_id=9)
    )
    first = telegram.add_update(
        chat_id="-1001",
        text="Answer",
        author="alice",
        message_thread_id=9,
        reply_to_message_id=sent.message_id,
    )
    telegram.add_update(chat_id="-1002", text="Other")

    assert sent.message_id == 1
    assert telegram.sent_messages[0].text == "Question"
    assert [update.update_id for update in telegram.poll_updates(TelegramPollUpdatesQuery())] == [
        first.update_id,
        first.update_id + 1,
    ]
    assert [
        update.update_id
        for update in telegram.poll_updates(TelegramPollUpdatesQuery(offset=first.update_id + 1))
    ] == [first.update_id + 1]


def test_telegram_bot_adapter_sends_without_exposing_token(monkeypatch) -> None:
    requests = []
    monkeypatch.setenv("TG_TEST_TOKEN", "secret-token")

    def requester(request, timeout):
        requests.append((request, timeout))
        return FakeResponse(
            {
                "ok": True,
                "result": {
                    "message_id": 12,
                    "chat": {"id": -1001},
                    "message_thread_id": 9,
                },
            }
        )

    adapter = TelegramBotApi(
        TelegramBotConfig(token_env_var="TG_TEST_TOKEN"),
        http_requester=requester,
    )

    reference = adapter.send_message(
        TelegramSendMessagePayload(chat_id="-1001", text="Question", message_thread_id=9)
    )

    assert reference.message_id == 12
    assert reference.chat_id == "-1001"
    assert reference.message_thread_id == 9
    assert requests[0][1] == 30.0
    assert "secret-token" in requests[0][0].full_url


def test_telegram_bot_adapter_parses_updates(monkeypatch) -> None:
    monkeypatch.setenv("TG_TEST_TOKEN", "secret-token")

    def requester(request, timeout):
        return FakeResponse(
            {
                "ok": True,
                "result": [
                    {
                        "update_id": 101,
                        "message": {
                            "message_id": 9,
                            "message_thread_id": 7,
                            "text": "fix",
                            "from": {"username": "alice"},
                            "chat": {"id": -1001},
                            "reply_to_message": {"message_id": 8},
                        },
                    }
                ],
            }
        )

    updates = TelegramBotApi(
        TelegramBotConfig(token_env_var="TG_TEST_TOKEN"),
        http_requester=requester,
    ).poll_updates(TelegramPollUpdatesQuery(offset=100, limit=5))

    assert len(updates) == 1
    assert updates[0].update_id == 101
    assert updates[0].chat_id == "-1001"
    assert updates[0].text == "fix"
    assert updates[0].author == "alice"
    assert updates[0].message_thread_id == 7
    assert updates[0].reply_to_message_id == 8


def test_telegram_bot_adapter_does_not_include_token_in_missing_env_error(monkeypatch) -> None:
    monkeypatch.delenv("TG_TEST_TOKEN", raising=False)
    adapter = TelegramBotApi(TelegramBotConfig(token_env_var="TG_TEST_TOKEN"))

    with pytest.raises(RuntimeError) as exc_info:
        adapter.poll_updates(TelegramPollUpdatesQuery())

    assert str(exc_info.value) == "Telegram token env var TG_TEST_TOKEN is empty"
