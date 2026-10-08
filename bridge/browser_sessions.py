"""Bridge-lifetime browser sessions and LAN phone pairing."""
import secrets
import re
import time
import hmac
import hashlib
import ipaddress
import json
import os
from http.cookies import SimpleCookie, CookieError
from pathlib import Path

COOKIE = 'nebulah_session'
MAX_SESSIONS = 32
PIN_ATTEMPT_WINDOW = 900
PIN_MAX_ATTEMPTS = 5
RESTART_GRACE_SECONDS = 180


class BrowserSessions:
    def __init__(self):
        self.sessions = set()
        self.waiting = set()
        self.phone_pin = f'{secrets.randbelow(1_000_000):06d}'
        self.phone_attempts = {}
        self.recoverable = set()
        self.recovery_target = None
        self.recovery_until = 0

    @staticmethod
    def _digest(value):
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    @staticmethod
    def _cookie_key(header):
        try:
            cookie = SimpleCookie()
            cookie.load(header or '')
            return cookie[COOKIE].value if COOKIE in cookie else ''
        except CookieError:
            return ''

    def issue_phone_pin(self, target, issuer):
        if not isinstance(target, str) or issuer not in self.sessions or issuer in self.waiting:
            raise ValueError('Connect a console before pairing a phone.')
        return self.phone_pin

    def check_phone_pin(self, pin, target, client):
        now = time.monotonic()
        attempts = [when for when in self.phone_attempts.get(client, ()) if now - when < PIN_ATTEMPT_WINDOW]
        if len(attempts) >= PIN_MAX_ATTEMPTS:
            self.phone_attempts[client] = attempts
            return 'locked'
        if (self.phone_pin is not None and isinstance(pin, str)
                and re.fullmatch(r'[0-9]{6}', pin) and isinstance(target, str)
                and hmac.compare_digest(pin, self.phone_pin)):
            self.phone_attempts.pop(client, None)
            return 'valid'
        attempts.append(now)
        self.phone_attempts[client] = attempts
        return 'invalid'

    def lookup(self, header):
        key = self._cookie_key(header)
        return key if key in self.sessions else None

    def recover(self, header, target):
        """Restore a former cookie only for the same connected target during grace."""
        key = self._cookie_key(header)
        digest = self._digest(key) if key else ''
        if not digest or digest not in self.recoverable:
            return None
        if time.time() > self.recovery_until:
            self.recoverable.clear()
            return None
        if target is None:
            return 'pending'
        if not isinstance(target, str) or self._digest(target.casefold()) != self.recovery_target:
            return 'wrong-target'
        if len(self.sessions) >= MAX_SESSIONS:
            return None
        self.recoverable.remove(digest)
        self.sessions.add(key)
        return 'restored'

    def save_handoff(self, path, target):
        """Persist only hashes of active session cookies for a brief local restart."""
        path = Path(path)
        active = [self._digest(key) for key in self.sessions if key not in self.waiting]
        try:
            address = ipaddress.ip_address(target) if isinstance(target, str) else None
        except ValueError:
            address = None
        trusted = isinstance(address, ipaddress.IPv4Address) and any(
            address in ipaddress.ip_network(block)
            for block in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
        if not trusted or not active:
            path.unlink(missing_ok=True)
            return False
        data = {'version': 1, 'until': int(time.time()) + RESTART_GRACE_SECONDS,
                'target': self._digest(str(address)), 'sessions': sorted(active)}
        path.parent.mkdir(parents=True, exist_ok=True)
        staged = path.with_name(path.name + '.new')
        staged.write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
        os.chmod(staged, 0o600)
        os.replace(staged, path)
        return True

    @classmethod
    def load_handoff(cls, path):
        sessions = cls()
        path = Path(path)
        try:
            if path.stat().st_size > 4096:
                return sessions
            data = json.loads(path.read_text(encoding='utf-8'))
            until = data.get('until')
            hashes = data.get('sessions')
            target = data.get('target')
            now = time.time()
            if (data.get('version') != 1 or type(until) is not int
                    or not now <= until <= now + RESTART_GRACE_SECONDS
                    or not isinstance(target, str) or not re.fullmatch('[0-9a-f]{64}', target)
                    or not isinstance(hashes, list) or len(hashes) > MAX_SESSIONS
                    or not all(isinstance(item, str) and re.fullmatch('[0-9a-f]{64}', item) for item in hashes)):
                return sessions
            sessions.recoverable = set(hashes)
            sessions.recovery_target = target
            sessions.recovery_until = until
        except (OSError, ValueError, TypeError):
            pass
        finally:
            try:path.unlink(missing_ok=True)
            except OSError:pass
        return sessions

    def create(self, waiting=False):
        if len(self.sessions) >= MAX_SESSIONS:
            raise ValueError('Too many paired browsers. Sign out an unused browser first.')
        key = secrets.token_urlsafe(32)
        self.sessions.add(key)
        if waiting:self.waiting.add(key)
        return key

    def activate(self, key):
        self.waiting.discard(key)

    def logout(self, key):
        self.sessions.discard(key)
        self.waiting.discard(key)
        self.recoverable.discard(self._digest(key))

    @staticmethod
    def cookie(key):
        # Browser restarts must not end a bridge-lifetime pairing. The server's
        # in-memory session set still invalidates this cookie when the bridge exits.
        age = 31536000 if key else 0
        return f'{COOKIE}={key}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}'
