"""Session grants in built-in OS credential vaults; no plaintext file fallback."""
import json
import os
import re
import sys
import time
import warnings


def _backend():
    if os.name == 'nt':
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    if sys.platform == 'darwin':
        from keyring.backends.macOS import Keyring
        return Keyring()
    from keyring.backends.SecretService import Keyring
    return Keyring()


def _service(origin):
    return 'EurusEdu SDK ' + origin


def load(origin, session_id):
    try:
        value = _backend().get_password(_service(origin), session_id)
        if not isinstance(value, str) or len(value) > 1024:
            return None
        grant = json.loads(value)
        cookie, expires = grant['cookie'], grant['expires_at']
        if (not isinstance(cookie, str) or not re.fullmatch(r'__Host-laserdrone-sdk=[A-Za-z0-9_-]{43}', cookie)
                or not isinstance(expires, (int, float)) or not time.time() + 5 < expires <= time.time() + 28800):
            return None
        return cookie, expires
    except Exception:
        return None  # Locked/unavailable vaults require browser approval.


def save(origin, session_id, cookie, expires_at):
    try:
        value = json.dumps({'cookie': cookie, 'expires_at': expires_at})
        _backend().set_password(_service(origin), session_id, value)
        return True
    except Exception:
        warnings.warn('OS credential storage unavailable; SDK approval will be reused only in this process.',
                      RuntimeWarning, stacklevel=2)
        return False


def delete(origin, session_id):
    try:
        _backend().delete_password(_service(origin), session_id)
    except Exception:
        pass
