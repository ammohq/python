"""The Flask handler must not turn HTTP errors into 500s."""

from unittest.mock import patch

import pytest

flask = pytest.importorskip("flask")

from booboo._client import BoobooClient  # noqa: E402


@pytest.fixture
def app_and_client():
    app = flask.Flask(__name__)

    @app.route("/boom")
    def boom():
        raise ValueError("boom")

    @app.route("/forbidden")
    def forbidden():
        flask.abort(403)

    @app.route("/teapot-500")
    def server_error():
        flask.abort(503)

    c = BoobooClient("test-dsn", endpoint="https://example.com/")
    c._install_flask(app)
    yield app, c
    c._flush()


def test_404_stays_404(app_and_client):
    app, c = app_and_client
    with patch.object(c, "_capture_and_send") as cap:
        resp = app.test_client().get("/nope")
    assert resp.status_code == 404
    cap.assert_not_called()


def test_abort_4xx_keeps_its_status(app_and_client):
    app, c = app_and_client
    with patch.object(c, "_capture_and_send") as cap:
        resp = app.test_client().get("/forbidden")
    assert resp.status_code == 403
    cap.assert_not_called()


def test_abort_5xx_is_captured_and_kept(app_and_client):
    app, c = app_and_client
    with patch.object(c, "_capture_and_send") as cap:
        resp = app.test_client().get("/teapot-500")
    assert resp.status_code == 503
    cap.assert_called_once()


def test_unhandled_exception_is_captured_and_500(app_and_client):
    app, c = app_and_client
    with patch.object(c, "_capture_and_send") as cap:
        resp = app.test_client().get("/boom")
    assert resp.status_code == 500
    assert isinstance(cap.call_args.args[0], ValueError)
