import atexit
import contextlib
import json
import logging
import os
import platform
import queue
import sys
import threading
import time
from urllib.parse import urlparse

import requests

from ._scrubber import scrub_headers
from ._stacktrace import extract_exception_chain, extract_frames

_SENTINEL = object()
DEFAULT_ENDPOINT = "https://ingest.booboo.dev/"

# Diagnostics go through the standard logging module, so they show up in the
# host app's logs (or on stderr via logging's last-resort handler when nothing
# is configured) instead of being swallowed. Warnings are rate-limited so a
# misconfigured DSN on a busy app doesn't flood the log.
logger = logging.getLogger("booboo")
_WARN_INTERVAL = 60.0


def _parse_dsn(dsn):
    """Return (token, endpoint_or_None).

    Accepts both bare tokens and URL-style DSNs like
    ``https://TOKEN@host[/path]``. The path is decorative — only the
    scheme + host are used to derive the ingest endpoint.
    """
    if isinstance(dsn, str) and dsn.startswith(("http://", "https://")):
        parsed = urlparse(dsn)
        if parsed.username and parsed.hostname:
            host = parsed.hostname
            if parsed.port:
                host = f"{host}:{parsed.port}"
            return parsed.username, f"{parsed.scheme}://{host}/"
    return dsn, None


class BoobooClient:
    def __init__(
        self,
        dsn,
        environment="",
        release=None,
        ignore_errors=None,
        endpoint=None,
        before_send=None,
        debug=False,
    ):
        token, derived_endpoint = _parse_dsn(dsn)
        self.dsn = token
        self.endpoint = endpoint or derived_endpoint or DEFAULT_ENDPOINT
        self.environment = environment
        self.release = release if release is not None else os.environ.get("BOOBOO_RELEASE", "")
        self.ignore_errors = tuple(ignore_errors) if ignore_errors else ()
        self.before_send = before_send
        self._orig_excepthook = None
        self._queue = queue.Queue(maxsize=100)
        self._worker = None
        self._worker_started = False
        self._lock = threading.Lock()
        self._user = None
        self._last_warning = {}
        self.debug = bool(debug) or os.environ.get("BOOBOO_DEBUG", "") in ("1", "true", "yes")
        if self.debug:
            logger.setLevel(logging.DEBUG)
            if not logger.handlers and not logging.getLogger().handlers:
                logger.addHandler(logging.StreamHandler())
            logger.debug(
                "booboo: initialised, endpoint=%s environment=%r", self.endpoint, environment
            )
        if not token:
            self._warn("no-dsn", "booboo: no DSN configured — events will not be sent")
        atexit.register(self._flush)

    def _warn(self, key, msg, *args):
        """logger.warning, at most once per _WARN_INTERVAL per key (always in debug)."""
        now = time.monotonic()
        last = self._last_warning.get(key, 0.0)
        if self.debug or now - last >= _WARN_INTERVAL:
            self._last_warning[key] = now
            logger.warning(msg, *args)

    def set_user(self, user_data):
        """Set user context for subsequent events."""
        self._user = user_data

    def install(self, app=None):
        """Hook sys.excepthook, auto-detect frameworks, register middleware/handlers."""
        self._orig_excepthook = sys.excepthook
        sys.excepthook = self._excepthook

        # Django: auto-detect -> inject middleware + patch exception handler
        try:
            from django.conf import settings

            mw = "booboo._middleware.BoobooDjangoMiddleware"
            mw_list = list(settings.MIDDLEWARE)
            if mw not in mw_list:
                mw_list.insert(0, mw)
                settings.MIDDLEWARE = mw_list

            from booboo._middleware import _patch_django_exception_handler

            _patch_django_exception_handler()
        except Exception:
            pass

        # Django Channels: auto-patch ProtocolTypeRouter
        self._patch_channels_router()

        # Flask: explicit app or auto-patch constructor
        if app is not None and self._is_flask(app):
            self._install_flask(app)
        else:
            try:
                import flask

                self._patch_flask_class(flask.Flask)
            except ImportError:
                pass

        # FastAPI: explicit app or auto-patch constructor
        if app is not None and self._is_fastapi(app):
            self._install_fastapi(app)
        else:
            try:
                import fastapi

                self._patch_fastapi_class(fastapi.FastAPI)
            except ImportError:
                pass

    def _is_flask(self, app):
        try:
            import flask

            return isinstance(app, flask.Flask)
        except ImportError:
            return False

    def _is_fastapi(self, app):
        try:
            import fastapi

            return isinstance(app, fastapi.FastAPI)
        except ImportError:
            return False

    def _install_flask(self, app):
        client = self

        @app.errorhandler(Exception)
        def _booboo_flask_handler(exc):
            # HTTP errors (404, 405, abort(403)...) are responses, not crashes.
            # Return them so Flask renders the proper status — re-raising from
            # an Exception handler turned every 404 into a 500.
            try:
                from werkzeug.exceptions import HTTPException

                if isinstance(exc, HTTPException):
                    # abort(503) is worth an event; Flask's own wrapping of an
                    # unhandled error (InternalServerError with original_exception)
                    # already came through here as the original — don't double-send.
                    if (exc.code or 0) >= 500 and getattr(exc, "original_exception", None) is None:
                        client._capture_and_send(exc)
                    return exc
            except ImportError:
                pass
            request_data = None
            user_data = None
            try:
                from flask import request

                headers = scrub_headers(dict(request.headers))
                request_data = {
                    "method": request.method,
                    "url": request.url,
                    "headers": headers,
                    "query_string": request.query_string.decode("utf-8", errors="replace"),
                }
                if request.remote_addr:
                    user_data = {"ip_address": request.remote_addr}
            except Exception:
                pass
            client._capture_and_send(exc, request_data=request_data, user_data=user_data)
            raise

        return _booboo_flask_handler

    def _install_fastapi(self, app):
        from booboo._middleware import BoobooASGIMiddleware

        app.add_middleware(BoobooASGIMiddleware)

    def _patch_flask_class(self, cls):
        """Monkey-patch Flask.__init__ to auto-register error handler."""
        client = self
        _original_init = cls.__init__

        def _patched_init(self_app, *args, **kwargs):
            _original_init(self_app, *args, **kwargs)
            client._install_flask(self_app)

        cls.__init__ = _patched_init

    def _patch_fastapi_class(self, cls):
        """Monkey-patch FastAPI.__init__ to auto-add ASGI middleware."""
        _original_init = cls.__init__

        def _patched_init(self_app, *args, **kwargs):
            _original_init(self_app, *args, **kwargs)
            from booboo._middleware import BoobooASGIMiddleware

            self_app.add_middleware(BoobooASGIMiddleware)

        cls.__init__ = _patched_init

    def _patch_channels_router(self):
        """Monkey-patch Django Channels ProtocolTypeRouter to capture errors."""
        try:
            from channels.routing import ProtocolTypeRouter
        except ImportError:
            return

        if getattr(ProtocolTypeRouter, "_booboo_patched", False):
            return

        client = self
        _original_call = ProtocolTypeRouter.__call__

        async def _wrapped_call(router_self, scope, receive, send):
            if scope["type"] == "lifespan":
                await _original_call(router_self, scope, receive, send)
                return
            try:
                await _original_call(router_self, scope, receive, send)
            except Exception as exc:
                from ._middleware import _extract_asgi_request

                request_data, user_data = _extract_asgi_request(scope)
                client._capture_and_send(exc, request_data=request_data, user_data=user_data)
                raise

        ProtocolTypeRouter.__call__ = _wrapped_call
        ProtocolTypeRouter._booboo_patched = True

    def _ensure_worker(self):
        """Lazily start the background worker thread. Returns False if thread creation fails."""
        if self._worker_started:
            return True
        with self._lock:
            if self._worker_started:
                return True
            try:
                self._worker = threading.Thread(target=self._worker_loop, daemon=True)
                self._worker.start()
                self._worker_started = True
                return True
            except RuntimeError:
                return False

    def _worker_loop(self):
        """Background thread: drain queue, send events, exit on sentinel."""
        while True:
            try:
                item = self._queue.get()
                try:
                    if item is _SENTINEL:
                        return
                    self._do_send(item)
                finally:
                    self._queue.task_done()
            except Exception:
                pass

    def _excepthook(self, exc_type, exc_value, exc_tb):
        self._capture_and_send(exc_value)
        if self._orig_excepthook:
            self._orig_excepthook(exc_type, exc_value, exc_tb)

    def capture_exception(self, exc=None):
        """Public API: capture an exception manually."""
        if exc is None:
            exc = sys.exc_info()[1]
        if exc is not None:
            self._capture_and_send(exc)

    def capture_message(self, message, level="info"):
        """Public API: send a plain message event."""
        from . import __version__

        context = {
            "sdk": {"name": "booboo-sdk", "version": __version__},
            "runtime": {"name": "Python", "version": platform.python_version()},
        }

        if self._user:
            context["user"] = dict(self._user)

        payload = {
            "message": message,
            "exception_type": "",
            "level": level,
            "stacktrace": [],
            "exceptions": [],
            "context": context,
            "tags": {"runtime": "python"},
            "environment": self.environment,
            "release": self.release,
        }

        self._enqueue(payload)

    def _capture_and_send(self, exc, request_data=None, user_data=None):
        if self.ignore_errors and isinstance(exc, self.ignore_errors):
            return

        try:
            frames = extract_frames(exc)
        except Exception:
            frames = []

        try:
            exceptions = extract_exception_chain(exc)
        except Exception:
            exceptions = []

        from . import __version__

        context = {
            "sdk": {"name": "booboo-sdk", "version": __version__},
            "runtime": {"name": "Python", "version": platform.python_version()},
        }

        # Merge user: auto-captured user_data takes priority, falls back to set_user()
        user = None
        if self._user:
            user = dict(self._user)
        if user_data:
            if user:
                user.update(user_data)
            else:
                user = user_data
        if user:
            context["user"] = user

        payload = {
            "message": str(exc),
            "exception_type": type(exc).__name__,
            "level": "error",
            "stacktrace": frames,
            "exceptions": exceptions,
            "context": context,
            "tags": {"runtime": "python"},
            "environment": self.environment,
            "release": self.release,
        }
        if request_data:
            payload["request"] = request_data

        self._enqueue(payload)

    def _enqueue(self, payload):
        try:
            if self._ensure_worker():
                try:
                    self._queue.put_nowait(payload)
                except queue.Full:
                    self._warn(
                        "queue-full",
                        "booboo: event dropped, send queue full (%d pending)",
                        self._queue.maxsize,
                    )
            else:
                self._do_send(payload)  # sync fallback
        except Exception as e:
            self._warn("enqueue", "booboo: could not queue event: %r", e)

    def _flush(self):
        """Wait for background worker to drain (called at exit)."""
        try:
            if not self._worker_started:
                return
            self._queue.put_nowait(_SENTINEL)
            self._worker.join(timeout=5)
        except Exception:
            pass

    def _apply_before_send(self, payload):
        """Run the before_send hook. Returns the payload to send, or None to drop.

        If the hook raises, the event is dropped: for a PII-scrubbing hook,
        sending the unscrubbed event on hook failure would be a leak.
        """
        if self.before_send is None:
            return payload
        try:
            return self.before_send(payload)
        except Exception:
            return None

    def _do_send(self, payload):
        try:
            payload = self._apply_before_send(payload)
            if payload is None:
                logger.debug("booboo: event dropped by before_send")
                return
            data = json.dumps(payload).encode("utf-8")
            if len(data) > 102_400:
                self._warn(
                    "too-large",
                    "booboo: event dropped, payload is %d bytes (limit 100 KB)",
                    len(data),
                )
                return
        except Exception as e:
            self._warn("serialise", "booboo: could not serialise event: %r", e)
            return
        try:
            resp = requests.post(
                self.endpoint,
                data=data,
                headers={"X-Booboo-DSN": self.dsn, "Content-Type": "application/json"},
                timeout=5,
            )
        except Exception as e:
            self._warn("transport", "booboo: could not reach %s: %r", self.endpoint, e)
            return
        status = getattr(resp, "status_code", None)
        if not isinstance(status, int) or 200 <= status < 300:
            logger.debug("booboo: event sent (HTTP %s)", status)
            return
        detail = ""
        with contextlib.suppress(Exception):
            detail = (resp.json() or {}).get("detail") or resp.text[:200]
        self._warn(
            f"http-{status}",
            "booboo: event rejected by %s: HTTP %s %s",
            self.endpoint,
            status,
            detail,
        )
