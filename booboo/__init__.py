from ._client import BoobooClient

__version__ = "0.14.0"

_client = None


def init(dsn, app=None, environment="", ignore_errors=None, endpoint=None, before_send=None):
    """Initialize booboo error tracking.

    ``dsn`` accepts either a bare token (``"abc123..."``) or a URL-style DSN
    (``"https://abc123...@ingest.booboo.dev/org-slug/project-slug"``). With a
    URL DSN, the ingest endpoint is derived from the URL automatically; pass
    ``endpoint=`` only to override.

    Always hooks sys.excepthook. Auto-detects Django, Flask, and FastAPI.
    Pass app= to explicitly register with a specific app instance.
    Pass environment= to tag all events with an environment (e.g. "production").
    Pass ignore_errors= to suppress specific exception types (uses isinstance matching).
    Pass before_send= to inspect or modify every event before transmission —
    useful for value-level PII scrubbing (IBANs, emails in variable values).
    The hook receives the event dict and must return it (possibly modified),
    or None to drop the event. If the hook raises, the event is dropped.
    """
    global _client
    _client = BoobooClient(
        dsn,
        environment=environment,
        ignore_errors=ignore_errors,
        endpoint=endpoint,
        before_send=before_send,
    )
    _client.install(app)


def capture_exception(exc=None):
    """Manually capture an exception. Uses sys.exc_info() if exc is None."""
    if _client:
        _client.capture_exception(exc)


def capture_message(message, level="info"):
    """Send a plain message event. Level: 'error', 'warning', or 'info'."""
    if _client:
        _client.capture_message(message, level)


def set_user(user_data):
    """Set user context (id, email, username, ip_address, etc.) for subsequent events."""
    if _client:
        _client.set_user(user_data)
