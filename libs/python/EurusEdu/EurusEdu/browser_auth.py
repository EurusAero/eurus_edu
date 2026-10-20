"""Browser approval for a single simulator session, cached in the OS vault."""
import json
import re
import threading
import time
import urllib.request
import webbrowser
from . import auth_store

_cache = {}
_lock = threading.Lock()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _cached(key):
    entry = _cache.get(key)
    if entry and entry[1] > time.monotonic():
        return entry[0]
    _cache.pop(key, None)
    saved = auth_store.load(*key)
    if saved:
        token, expires_at = saved
        _cache[key] = token, time.monotonic() + expires_at - time.time() - 5
        return token
    return None


def approve(origin, session_id, context, timeout=120, invalidate=False):
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 300:
        raise ValueError("SDK approval timeout must be 1–300 seconds")
    key = (origin, session_id)
    with _lock:
        if invalidate:
            _cache.pop(key, None)
            auth_store.delete(*key)
        cached = None if invalidate else _cached(key)
        if cached:
            return cached
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _NoRedirect())
        prefix = f"{origin}/s/{session_id}/sdk"
        deadline = time.monotonic() + timeout

        def post(path, payload):
            request = urllib.request.Request(prefix + path, json.dumps(payload).encode(),
                {"Content-Type": "application/json", "Origin": origin}, method="POST")
            try:
                with opener.open(request, timeout=min(10, max(.1, deadline - time.monotonic()))) as response:
                    data = response.read(16385)
                    if response.status != 200 or len(data) > 16384:
                        raise ValueError("Invalid authorization response")
                    return json.loads(data)
            except Exception:
                raise ConnectionError("SDK browser authorization failed") from None

        device = post("/device", {})
        code, user_code = device.get("device_code", ""), device.get("user_code", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", code) or not re.fullmatch(r"[a-f0-9]{16}", user_code):
            raise ConnectionError("Invalid SDK approval request")
        expected = prefix + "/authorize?code=" + user_code
        if device.get("verification_uri") != expected:
            raise ConnectionError("SDK approval must use the simulator origin")
        print(f"Разрешите подключение SDK в браузере. Код: {user_code}\n{expected}")
        try:
            webbrowser.open(expected)
        except Exception:
            pass  # The displayed same-origin link also works in a manually opened browser.
        deadline = min(deadline, time.monotonic() + min(120, device.get("expires_in", 120)))
        while time.monotonic() < deadline:
            result = post("/token", {"device_code": code})
            if result.get("state") == "denied":
                raise PermissionError("SDK connection rejected in the browser")
            if result.get("state") == "approved":
                token = result.get("cookie", "")
                if not re.fullmatch(r"__Host-laserdrone-sdk=[A-Za-z0-9_-]{43}", token):
                    raise ConnectionError("Invalid SDK authorization response")
                expires = result.get("expires_in", 0)
                if not isinstance(expires, (int, float)) or not 0 < expires <= 28800:
                    raise ConnectionError("Invalid SDK authorization lifetime")
                _cache[key] = token, time.monotonic() + expires - 5
                auth_store.save(origin, session_id, token, time.time() + expires)
                return token
            if result.get("state") != "pending":
                raise ConnectionError("SDK approval request expired")
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise TimeoutError("SDK approval timed out")


def cached_cookie(origin, session_id):
    with _lock:
        return _cached((origin, session_id))
