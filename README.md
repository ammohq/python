# booboo-sdk

[![CI](https://github.com/getbooboo/python/actions/workflows/ci.yml/badge.svg)](https://github.com/getbooboo/python/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/booboo-sdk.svg)](https://pypi.org/project/booboo-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/booboo-sdk.svg)](https://pypi.org/project/booboo-sdk/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Official Python SDK for [booboo.dev](https://booboo.dev) error tracking.

## Installation

```bash
pip install booboo-sdk
```

## Quick Start

```python
import booboo

booboo.init("https://YOUR_TOKEN@ingest.booboo.dev/your-org/your-project")
```

That's it. Unhandled exceptions are automatically captured and sent to booboo.dev.

The DSN is a URL — the SDK parses out the ingest host so you don't need to configure an endpoint separately. Bare tokens (e.g. `"abc123..."`) are also accepted for back-compat with older dashboards.

## Manual Capture

```python
try:
    risky_operation()
except Exception:
    booboo.capture_exception()  # captures the current exception
```

Or pass an exception explicitly:

```python
try:
    risky_operation()
except Exception as e:
    booboo.capture_exception(e)
```

## User Context

```python
booboo.set_user({
    "id": "123",
    "email": "user@example.com",
    "username": "alice",
})
```

## Framework Integration

### Django

Auto-detected — no extra setup needed. The SDK injects middleware and patches Django's internal exception handler to capture errors that never reach middleware (like `DisallowedHost`). 404 errors are filtered by default.

### Flask

```python
from flask import Flask
import booboo

app = Flask(__name__)
booboo.init("https://YOUR_TOKEN@ingest.booboo.dev/your-org/your-project", app=app)
```

Or without passing `app` — the SDK monkey-patches `Flask.__init__` to auto-register on any Flask app created after `init()`. 404 errors are filtered by default.

### FastAPI

```python
from fastapi import FastAPI
import booboo

app = FastAPI()
booboo.init("https://YOUR_TOKEN@ingest.booboo.dev/your-org/your-project", app=app)
```

Same auto-detection as Flask if `app` is not passed explicitly.

## Configuration

```python
booboo.init(
    dsn="https://YOUR_TOKEN@ingest.booboo.dev/your-org/your-project",
    environment="production",
    release="1.4.2",
    ignore_errors=[KeyboardInterrupt, ConnectionError],
)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `dsn` | (required) | Your project's DSN from booboo.dev |
| `app` | `None` | Flask/FastAPI app instance for explicit registration |
| `environment` | `""` | Environment name (e.g. `"production"`, `"staging"`). Attached to every event. |
| `release` | `BOOBOO_RELEASE` env var, or `""` | Release/version identifier (e.g. a git SHA or `"1.4.2"`). Attached to every event; powers "introduced in release X" on issues. |
| `ignore_errors` | `None` | List of exception classes to suppress. Uses `isinstance()` so subclasses are matched. |
| `endpoint` | derived from DSN URL, or `https://ingest.booboo.dev/` | Override the ingest endpoint. Normally unnecessary — the SDK derives it from the DSN URL automatically. |
| `before_send` | `None` | Hook called with the event dict before every send. Return the (possibly modified) event, or `None` to drop it. If the hook raises, the event is dropped. |

## before_send Hook

Use `before_send` to inspect or modify events before they leave your server. Return the
event to send it, or `None` to drop it:

```python
def drop_health_checks(event):
    if "/healthz" in event.get("message", ""):
        return None  # drop
    return event

booboo.init(
    dsn="https://YOUR_TOKEN@ingest.booboo.dev/your-org/your-project",
    before_send=drop_health_checks,
)
```

The hook receives every event (exceptions and `capture_message()` calls alike) and runs on
the SDK's background sender thread, so it never adds latency to your request path. If the
hook raises, the event is dropped — never sent unmodified.

### Value-level PII scrubbing

The SDK already scrubs sensitive variables *by name* (`password`, `token`, …), but only
your code knows which *values* are sensitive. A thorough scrubber must visit every place
values appear: the message, the top-level stacktrace's variables, and each chained
exception's message and frames:

```python
import re

IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")

def scrub_ibans(event):
    all_frames = list(event.get("stacktrace", []))
    for exc in event.get("exceptions", []):
        all_frames.extend(exc.get("stacktrace", []))
        exc["value"] = IBAN_RE.sub("[iban]", exc.get("value", ""))
    for frame in all_frames:
        for name, value in frame.get("vars", {}).items():
            frame["vars"][name] = IBAN_RE.sub("[iban]", value)
    event["message"] = IBAN_RE.sub("[iban]", event.get("message", ""))
    return event

booboo.init(
    dsn="https://YOUR_TOKEN@ingest.booboo.dev/your-org/your-project",
    before_send=scrub_ibans,
)
```

## Features

- Automatic capture of unhandled exceptions
- Rich stack traces with source context and local variables
- Exception chain support (`raise ... from ...`)
- PII scrubbing for sensitive headers and variables
- Django, Flask, and FastAPI integrations
- Non-blocking event delivery
- Graceful shutdown flush
- Minimal dependency footprint (`requests` only)

## License

MIT
