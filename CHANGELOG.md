# Changelog

## 0.15.0 (2026-08-20)

### Fixes

- **Flask: HTTP errors are no longer turned into 500s.** The error handler returned a bare `raise` for everything but `NotFound`, so `abort(403)`, 405s and friends surfaced as Internal Server Errors. `HTTPException`s are now returned as-is (5xx ones are still reported); only unhandled exceptions are captured and re-raised.
- **Delivery failures are logged.** A rejected event (wrong DSN → 403, quota → 429, oversized payload) or an unreachable endpoint used to fail silently. They now emit `logger.warning` on the `booboo` logger (rate-limited to once per minute per cause), so a broken install is visible in your app log instead of looking like "no errors yet".

### Features

- **`debug` option**: `booboo.init(..., debug=True)` (or `BOOBOO_DEBUG=1`) logs every send and drop on the `booboo` logger.

- **`release` option**: New `release` parameter on `booboo.init()` (and `BoobooClient`). Tags every event with a release/version identifier (e.g. a git SHA or `"1.4.2"`), enabling release tracking on issues ("introduced in release X", per-release filtering). Falls back to the `BOOBOO_RELEASE` environment variable when unset.

## 0.14.0 (2026-06-09)

### Features

- **`before_send` hook**: New `before_send` parameter on `booboo.init()` (and `BoobooClient`). The hook receives every event dict before transmission and must return it (possibly modified), or `None` to drop the event. Enables value-level PII scrubbing (IBANs, payment references, emails inside variable values) that the built-in name-based scrubber cannot do. If the hook raises, the event is dropped — never sent unscrubbed. Runs on the background sender thread, off the request path.

## 0.13.0 (2026-05-13)

### Features

- **URL-style DSNs**: `booboo.init(dsn)` now accepts both bare tokens and URL DSNs (e.g. `https://TOKEN@ingest.booboo.dev/your-org/your-project`). The SDK parses the URL to derive the ingest endpoint and sends only the token in the `X-Booboo-DSN` header — no need to pass `endpoint=` separately. Bare-token DSNs continue to work unchanged.

### Changed

- **Default ingest endpoint is now `https://ingest.booboo.dev/`** (previously `https://api.booboo.dev/ingest/`). Existing installs that pass `endpoint=` explicitly are unaffected. `api.booboo.dev/ingest/` continues to accept events from older SDK versions.

## 0.12.0 (2026-03-12)

### Changed

- **404 errors are now filtered by default** in Django and Flask integrations. Use `booboo.capture_exception()` in a custom 404 handler if you still want to track them.

## 0.11.0 (2026-03-11)

### Features

- **Django Channels support**: `ProtocolTypeRouter` is automatically patched when `channels` is installed — errors in both HTTP and WebSocket handlers are captured with full request context.
- **WebSocket error capture**: ASGI middleware now captures errors in WebSocket connections (previously only HTTP requests were handled).

## 0.10.0 (2026-03-03)

### Features

- **`capture_message()`**: Send plain message events (not tied to an exception) with `booboo.capture_message(message, level)`. Useful for tracking deployments, warnings, or custom events.
- **`ignore_errors`**: New `ignore_errors` parameter on `booboo.init()` to suppress known exception types from being reported. Uses `isinstance()` matching, so subclasses are automatically caught (e.g. `ignore_errors=[OSError]` also suppresses `ConnectionError`).

### Changed

- **`endpoint` parameter moved to end of argument list** in both `booboo.init()` and `BoobooClient.__init__()`. The default value (`https://api.booboo.dev/ingest/`) is now set directly on both functions. If you were passing `endpoint` as a positional argument, switch to the keyword form: `booboo.init("dsn", endpoint="...")`.

## 0.9.0 (2026-02-23)

### Features

- **Environment support**: `booboo.init()` now accepts an `environment` parameter (e.g. `"production"`, `"staging"`). The value is attached to every event and can be used to filter issues in the dashboard.

## 0.8.0 (2026-02-22)

### Fixed

- **SDK no longer crashes user applications** when thread creation fails (e.g., during interpreter shutdown). Replaced thread-per-event model with a single background worker thread + bounded queue — the same pattern used by Sentry's Python SDK.
- Fixed memory leak: completed thread objects were accumulated indefinitely in long-running processes.
- ASGI middleware no longer crashes on malformed request headers.

### Improved

- Event payloads exceeding 100KB are silently dropped instead of failing on the server.
- Local variable capture limited to 50 per frame to prevent oversized payloads.

## 0.7.0 (2026-02-20)

### Features

- Automatic exception capture via `sys.excepthook`
- Manual capture with `booboo.capture_exception()`
- User context with `booboo.set_user()`
- Rich stack traces with source context and local variables
- PII scrubbing for sensitive headers and local variables
- Exception chain support (`__cause__` and `__context__`)
- Framework integrations:
  - **Django**: automatic middleware injection + internal exception capture
  - **Flask**: error handler registration (explicit or monkey-patched)
  - **FastAPI**: ASGI middleware (explicit or monkey-patched)
- Non-blocking event delivery via background threads
- Graceful shutdown with `atexit` flush
