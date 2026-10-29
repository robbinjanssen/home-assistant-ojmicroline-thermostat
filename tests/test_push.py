"""Tests for the push updates of WD5-series thermostats."""

# pylint: disable=protected-access

from unittest.mock import MagicMock

import pytest
from ojmicroline_thermostat import OJMicrolineError

from custom_components.ojmicroline_thermostat.push import WD5PushClient


def _client() -> tuple[WD5PushClient, MagicMock, MagicMock]:
    client, api, on_message, _ = _client_with_connection()
    return client, api, on_message


def _client_with_connection() -> tuple[WD5PushClient, MagicMock, MagicMock, MagicMock]:
    api = MagicMock()
    on_message = MagicMock()
    on_connection_change = MagicMock()
    client = WD5PushClient(
        MagicMock(), MagicMock(), api, on_message, on_connection_change
    )
    return client, api, on_message, on_connection_change


def test_message() -> None:
    """Test pushed data is passed on."""
    client, api, on_message = _client()

    client._handle_payload('{"M": [{"Groups": []}]}')

    on_message.assert_called_once_with({"Groups": []})
    api.invalidate_session.assert_not_called()


def test_keep_alive() -> None:
    """Test keep-alive frames are ignored."""
    client, _, on_message = _client()

    client._handle_payload("{}")

    on_message.assert_not_called()


def test_rejected_session() -> None:
    """Test a rejected session ID ends the connection with a new session."""
    client, api, on_message = _client()

    with pytest.raises(OJMicrolineError):
        client._handle_payload('{"M": ["\\"No Way\\""]}')

    api.invalidate_session.assert_called_once()
    on_message.assert_not_called()


def test_session_accepted() -> None:
    """Test the connection counts as established once the hub accepts the session."""
    client, api, on_message, on_connection_change = _client_with_connection()

    client._handle_payload('{"M": ["\\"got it\\""]}')

    on_connection_change.assert_called_once_with(True)  # noqa: FBT003
    api.invalidate_session.assert_not_called()
    on_message.assert_not_called()


def test_message_marks_connected() -> None:
    """Test pushed data marks the connection as established."""
    client, _, _, on_connection_change = _client_with_connection()

    client._handle_payload('{"M": [{"Groups": []}]}')

    on_connection_change.assert_called_once_with(True)  # noqa: FBT003


def test_unknown_message() -> None:
    """Test an unknown message is ignored instead of treated as a rejection."""
    client, api, on_message, on_connection_change = _client_with_connection()

    client._handle_payload('{"M": ["\\"something else\\""]}')

    api.invalidate_session.assert_not_called()
    on_message.assert_not_called()
    on_connection_change.assert_not_called()
