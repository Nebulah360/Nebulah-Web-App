"""Opt-in Discord Rich Presence over the local desktop IPC pipe."""
import json
import os
import re
import struct
import threading
import time


def _frame(opcode, payload):
    body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    if len(body) > 65536:
        raise ValueError('Discord activity is too large.')
    return struct.pack('<II', opcode, len(body)) + body


def _read(pipe):
    def exact(length):
        result = bytearray()
        while len(result) < length:
            part = pipe.read(length - len(result))
            if not part:
                raise OSError('Discord IPC closed.')
            result.extend(part)
        return bytes(result)
    opcode, length = struct.unpack('<II', exact(8))
    if length > 65536:
        raise OSError('Discord IPC frame too large.')
    return opcode, json.loads(exact(length))


def _title(title):
    if not isinstance(title, dict):
        return None
    ident = title.get('title_id')
    path = title.get('executable')
    if not isinstance(ident, str) or not re.fullmatch(r'[0-9A-Fa-f]{8}', ident):
        return None
    if ident.upper() == 'FFFE07D1':
        return 'Xbox 360 Dashboard'
    if not isinstance(path, str):
        return 'Xbox 360 game'
    parts = path.replace('/', '\\').split('\\')
    folder = parts[-2].strip() if len(parts) > 1 else ''
    if folder.lower() in ('games', 'apps', 'homebrew', 'content') or not 2 <= len(folder) <= 80 or not folder.isprintable():
        return 'Xbox 360 game'
    return folder


class DiscordPresence:
    def __init__(self, pipe_open=open):
        self.pipe_open = pipe_open
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.thread = None
        self.pipe = None
        self.client_id = None
        self.asset_key = 'nebulah_n'
        self.title = None
        self.updated_at = 0
        self.state = 'disabled'

    def snapshot(self):
        with self.lock:
            return {'state': self.state, 'enabled': self.client_id is not None,
                    'image_key': self.asset_key if self.client_id else None}

    def start(self, client_id, asset_key, title):
        if not isinstance(client_id, str) or not re.fullmatch(r'[0-9]{17,20}', client_id):
            raise ValueError('Enter a Discord application ID of 17–20 digits.')
        if not isinstance(asset_key, str) or not re.fullmatch(r'[a-z0-9_-]{1,64}', asset_key):
            raise ValueError('Enter a lowercase Discord image asset key.')
        with self.lock:
            if self.client_id is not None:
                raise ValueError('Stop Discord activity before changing its application.')
            if self.thread is not None and self.thread.is_alive():
                raise ValueError('Discord activity is still stopping. Try again shortly.')
            self.client_id, self.asset_key = client_id, asset_key
            self.title, self.updated_at = _title(title), time.monotonic()
            self.state = 'connecting'
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, name='discord-presence', daemon=True)
            self.thread.start()
        return self.snapshot()

    def update(self, title):
        with self.lock:
            if self.client_id is None:
                return
            self.title, self.updated_at = _title(title), time.monotonic()
        self.wake.set()

    def stop(self):
        with self.lock:
            self.client_id = None
            self.state = 'disabled'
            thread = self.thread
            self.stop_event.set()
        self.wake.set()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        with self.lock:
            pipe = self.pipe
        if pipe:
            try:pipe.close()
            except OSError:pass
        return self.snapshot()

    def _open(self, client_id):
        for index in range(10):
            try:
                pipe = self.pipe_open(r'\\.\pipe\discord-ipc-' + str(index), 'r+b', buffering=0)
            except OSError:
                continue
            try:
                pipe.write(_frame(0, {'v': 1, 'client_id': client_id}))
                opcode, reply = _read(pipe)
                if opcode != 1 or reply.get('evt') != 'READY':
                    raise OSError('Discord rejected the application.')
                return pipe
            except (OSError, ValueError, TypeError):
                pipe.close()
                raise
        raise OSError('Discord desktop IPC is unavailable.')

    def _send(self, pipe, title, asset_key):
        activity = None if title is None else {
            'details': ('Playing ' + title)[:128], 'state': 'Xbox 360 via Nebulah Link',
            'assets': {'large_image': asset_key, 'large_text': 'Nebulah Link'}}
        pipe.write(_frame(1, {'cmd': 'SET_ACTIVITY', 'args': {'pid': os.getpid(), 'activity': activity},
                              'nonce': str(time.monotonic_ns())}))
        opcode, reply = _read(pipe)
        if opcode != 1 or reply.get('evt') == 'ERROR' or reply.get('cmd') != 'SET_ACTIVITY':
            raise OSError('Discord did not accept the activity.')

    def _run(self):
        sent = object()
        while not self.stop_event.is_set():
            with self.lock:
                client_id, asset_key = self.client_id, self.asset_key
            if client_id is None:
                return
            try:
                pipe = self._open(client_id)
                with self.lock:
                    if self.client_id != client_id:
                        pipe.close()
                        return
                    self.pipe = pipe
                sent = object()
                while not self.stop_event.is_set():
                    with self.lock:
                        title = self.title if time.monotonic() - self.updated_at < 90 else None
                    if title != sent:
                        self._send(pipe, title, asset_key)
                        sent = title
                        with self.lock:
                            if self.client_id is not None:self.state = 'active'
                    self.wake.wait(15)
                    self.wake.clear()
                try:self._send(pipe, None, asset_key)
                except (OSError, ValueError, TypeError):pass
            except (OSError, ValueError, TypeError):
                with self.lock:
                    if self.client_id is not None:self.state = 'unavailable'
                self.stop_event.wait(15)
            finally:
                with self.lock:
                    pipe = self.pipe
                    self.pipe = None
                if pipe:
                    try:pipe.close()
                    except OSError:pass
