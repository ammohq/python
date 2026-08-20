"""init() announces itself so the project shows "connected" before any error."""

import json
from unittest.mock import MagicMock, patch

from booboo._client import BoobooClient


def _sent(post):
    return [json.loads(c.kwargs["data"]) for c in post.call_args_list]


def test_install_sends_handshake():
    c = BoobooClient("test-dsn", endpoint="https://example.com/")
    with patch("requests.post", return_value=MagicMock(status_code=200)) as post:
        c.install()
        c._flush()
    payloads = _sent(post)
    assert len(payloads) == 1
    assert payloads[0]["handshake"] is True
    assert payloads[0]["sdk"].startswith("python/")
    assert post.call_args.kwargs["headers"]["X-Booboo-DSN"] == "test-dsn"


def test_handshake_can_be_disabled(monkeypatch):
    monkeypatch.setenv("BOOBOO_HANDSHAKE", "0")
    c = BoobooClient("test-dsn", endpoint="https://example.com/")
    with patch("requests.post") as post:
        c.install()
        c._flush()
    post.assert_not_called()


def test_no_handshake_without_dsn():
    c = BoobooClient("", endpoint="https://example.com/")
    with patch("requests.post") as post:
        c.install()
        c._flush()
    post.assert_not_called()


def test_before_send_does_not_see_handshake():
    hook = MagicMock(side_effect=AssertionError("hook must not run for handshake"))
    c = BoobooClient("test-dsn", endpoint="https://example.com/", before_send=hook)
    with patch("requests.post", return_value=MagicMock(status_code=200)) as post:
        c.install()
        c._flush()
    assert len(_sent(post)) == 1
    hook.assert_not_called()
