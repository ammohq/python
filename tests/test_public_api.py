import pytest

import booboo
from booboo._client import BoobooClient


@pytest.fixture(autouse=True)
def reset_client():
    """Reset the global client between tests."""
    booboo._client = None
    yield
    if booboo._client:
        booboo._client._flush()
    booboo._client = None


# --- init ---


def test_init_creates_client():
    booboo.init("test-dsn", endpoint="https://example.com/ingest/")
    assert isinstance(booboo._client, BoobooClient)


def test_init_sets_dsn():
    booboo.init("my-dsn", endpoint="https://example.com/ingest/")
    assert booboo._client.dsn == "my-dsn"


def test_init_sets_endpoint():
    booboo.init("dsn", endpoint="https://custom.example.com/ingest/")
    assert booboo._client.endpoint == "https://custom.example.com/ingest/"


def test_init_sets_environment():
    booboo.init("dsn", endpoint="https://example.com/ingest/", environment="staging")
    assert booboo._client.environment == "staging"


def test_init_sets_before_send():
    def hook(event):
        return event

    booboo.init("dsn", endpoint="https://example.com/ingest/", before_send=hook)
    assert booboo._client.before_send is hook


# --- capture_exception delegates ---


def test_capture_exception_delegates():
    booboo.init("dsn", endpoint="https://example.com/ingest/")
    calls = []
    booboo._client.capture_exception = lambda exc=None: calls.append(exc)

    exc = ValueError("test")
    booboo.capture_exception(exc)
    assert calls == [exc]


def test_capture_exception_noop_when_uninitialized():
    # Should not raise
    booboo.capture_exception(ValueError("test"))


# --- set_user delegates ---


def test_set_user_delegates():
    booboo.init("dsn", endpoint="https://example.com/ingest/")
    booboo.set_user({"id": "42"})
    assert booboo._client._user == {"id": "42"}


def test_set_user_noop_when_uninitialized():
    # Should not raise
    booboo.set_user({"id": "42"})


# --- capture_message delegates ---


def test_capture_message_delegates():
    booboo.init("dsn")
    calls = []
    booboo._client.capture_message = lambda msg, level="info": calls.append((msg, level))

    booboo.capture_message("hello")
    assert calls == [("hello", "info")]


def test_capture_message_noop_when_uninitialized():
    # Should not raise
    booboo.capture_message("hello")
