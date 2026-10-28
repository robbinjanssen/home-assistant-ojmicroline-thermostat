"""Tests for the push updates of WD5-series thermostats."""

# pylint: disable=protected-access

from unittest.mock import MagicMock

import pytest
from ojmicroline_thermostat import OJMicrolineError

from custom_components.ojmicroline_thermostat.push import WD5PushClient


def _client() -> tuple[WD5PushClient, MagicMock, MagicMock]:
    api = MagicMock()
    on_message = MagicMock()
    client = WD5PushClient(MagicMock(), MagicMock(), api, on_message, MagicMock())
    return client, api, on_message


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
