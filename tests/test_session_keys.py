from __future__ import annotations

from shared.session_keys import session_key_for_message


def test_session_key_for_private_telegram_chat():
    payload = {"chat_type": "private", "chat_id": 123, "principal_external_id": "u1"}
    assert session_key_for_message("telegram", payload) == "private_main"


def test_session_key_for_telegram_group_topic():
    payload = {"chat_type": "supergroup", "chat_id": -1001, "message_thread_id": 77, "principal_external_id": "u1"}
    assert session_key_for_message("telegram", payload) == "group_-1001_topic_77"


def test_session_key_for_telegram_group_without_topic():
    payload = {"chat_type": "group", "chat_id": -55, "principal_external_id": "u1"}
    assert session_key_for_message("telegram", payload) == "group_-55_topic_main"


def test_session_key_for_non_telegram_channel():
    payload = {"principal_external_id": "u1"}
    assert session_key_for_message("cli", payload) == "cli_u1"
