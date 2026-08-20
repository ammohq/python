"""Delivery failures must be visible: a 403 from a wrong DSN used to vanish."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from booboo._client import BoobooClient


@pytest.fixture
def client():
    c = BoobooClient("test-dsn", endpoint="https://example.com/")
    yield c
    c._flush()


def _resp(status, body=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    r.text = text
    return r


def test_2xx_is_silent(client, caplog):
    with (
        patch("requests.post", return_value=_resp(201, {})),
        caplog.at_level(logging.WARNING, logger="booboo"),
    ):
        client._do_send({"message": "x"})
    assert caplog.records == []


def test_non_2xx_warns_with_server_detail(client, caplog):
    with (
        patch("requests.post", return_value=_resp(403, {"detail": "Invalid DSN."})),
        caplog.at_level(logging.WARNING, logger="booboo"),
    ):
        client._do_send({"message": "x"})
    assert len(caplog.records) == 1
    msg = caplog.records[0].getMessage()
    assert "HTTP 403" in msg and "Invalid DSN." in msg and "https://example.com/" in msg


def test_transport_error_warns(client, caplog):
    with (
        patch("requests.post", side_effect=OSError("refused")),
        caplog.at_level(logging.WARNING, logger="booboo"),
    ):
        client._do_send({"message": "x"})
    assert "could not reach https://example.com/" in caplog.text


def test_too_large_warns(client, caplog):
    with (
        patch("requests.post") as post,
        caplog.at_level(logging.WARNING, logger="booboo"),
    ):
        client._do_send({"message": "x" * 200_000})
    post.assert_not_called()
    assert "limit 100 KB" in caplog.text


def test_warnings_are_rate_limited_per_cause(client, caplog):
    with (
        patch("requests.post", return_value=_resp(403, {"detail": "Invalid DSN."})),
        caplog.at_level(logging.WARNING, logger="booboo"),
    ):
        for _ in range(5):
            client._do_send({"message": "x"})
    assert len(caplog.records) == 1
    # A different cause still gets through.
    with (
        patch("requests.post", return_value=_resp(429, {"detail": "Quota."})),
        caplog.at_level(logging.WARNING, logger="booboo"),
    ):
        client._do_send({"message": "x"})
    assert len(caplog.records) == 2


def test_debug_logs_each_send(caplog):
    c = BoobooClient("test-dsn", endpoint="https://example.com/", debug=True)
    try:
        with (
            patch("requests.post", return_value=_resp(201, {})),
            caplog.at_level(logging.DEBUG, logger="booboo"),
        ):
            c._do_send({"message": "x"})
        assert "event sent (HTTP 201)" in caplog.text
    finally:
        c._flush()
        logging.getLogger("booboo").setLevel(logging.NOTSET)


def test_debug_env_var(monkeypatch):
    monkeypatch.setenv("BOOBOO_DEBUG", "1")
    c = BoobooClient("test-dsn", endpoint="https://example.com/")
    try:
        assert c.debug is True
    finally:
        c._flush()
        logging.getLogger("booboo").setLevel(logging.NOTSET)


def test_empty_dsn_warns_at_init(caplog):
    with caplog.at_level(logging.WARNING, logger="booboo"):
        c = BoobooClient("", endpoint="https://example.com/")
    c._flush()
    assert "no DSN configured" in caplog.text
