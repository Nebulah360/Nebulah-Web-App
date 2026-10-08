"""Bounded, opt-in receiver for the locally supplied 360Stream v38 protocol."""
import ipaddress
import os
import socket
import struct
import threading
import time
from collections import deque


HEADER = struct.Struct('>IBBHHHIIII')
MAGIC = 0x48593337
MAX_PAYLOAD = 2 * 1024 * 1024
MAX_BROWSER_JPEG = 1024 * 1024
MAX_BROWSER_AUDIO = 16 * 1024
# Dynamic JPEG and 48 kHz/16-bit stereo. Audio stays off until explicitly enabled.
INITIAL_CONTROL = b'DQTWZK~LLO'
STATUSES = frozenset(('AV_STREAM_V38_CONNECTED', 'AUDIO_HOOK_INSTALLED',
                      'STOPPING_AUDIO', 'STOPPING_WORKERS', 'SAFE_TO_UNLOAD'))


class Stream360Receiver:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.listener = None
        self.client = None
        self.thread = None
        self.expected_ip = None
        self.port = None
        self.state = 'stopped'
        self.listening_since = None
        self.last_status = None
        self.last_error = None
        self.safe_to_unload = False
        self.preparing_unload = False
        self.video_frames = 0
        self.audio_packets = 0
        self.video_codec = None
        self.frame_sequence = 0
        self.latest_jpeg = None
        self.audio_enabled = False
        self.audio_sequence = 0
        self.audio_queue = deque(maxlen=32)

    def status(self):
        with self.lock:
            return {'state':self.state, 'port':self.port, 'connected':self.client is not None,
                    'waiting_seconds':self.waiting_seconds_unlocked(),
                    'video_frames':self.video_frames, 'audio_packets':self.audio_packets,
                    'last_status':self.last_status, 'last_error':self.last_error,
                    'safe_to_unload':self.safe_to_unload,
                    'preparing_unload':self.preparing_unload,
                    'video_codec':self.video_codec,
                    'browser_frame_available':self.latest_jpeg is not None,
                    'audio_enabled':self.audio_enabled}

    def waiting_seconds_unlocked(self):
        if self.state != 'listening' or self.listening_since is None:return 0
        return max(0,int(time.monotonic()-self.listening_since))

    def frame(self, after):
        if type(after) is not int or after < 0:
            raise ValueError('Valid frame sequence required.')
        with self.lock:
            return (self.frame_sequence,self.latest_jpeg if self.frame_sequence > after else None,
                    self.video_codec)

    def audio(self, after):
        if type(after) is not int or after < 0:
            raise ValueError('Valid audio sequence required.')
        with self.lock:
            return self.audio_sequence, [packet for packet in self.audio_queue if packet[0] > after]

    def set_audio(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Choose whether browser audio is enabled.')
        with self.lock:
            if self.listener is None:
                raise ValueError('Start the receiver before changing audio.')
            if self.client is not None:
                try:self.client.sendall(b'J' if enabled else b'K')
                except OSError:raise ValueError('Could not change console audio streaming.') from None
            self.audio_enabled = enabled
            self.audio_queue.clear()
            return self.status_unlocked()

    def start(self, expected_ip, bind_host='0.0.0.0', port=36000):
        address = ipaddress.ip_address(expected_ip)
        if address.version != 4:
            raise ValueError('Choose a console IPv4 address.')
        with self.lock:
            if self.listener is not None:
                raise ValueError('Stream receiver is already running.')
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                if os.name == 'nt':
                    # SO_REUSEADDR permits a second Windows listener on the
                    # same port, leaving console connections nondeterministic.
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((bind_host,port))
                listener.listen(1)
                listener.settimeout(0.5)
            except OSError:
                listener.close()
                raise ValueError('Could not open Stream360 TCP port 36000 on this PC.') from None
            self.stop_event.clear()
            self.listener = listener
            self.expected_ip = str(address)
            self.port = listener.getsockname()[1]
            self.state = 'listening'
            self.listening_since = time.monotonic()
            self.last_status = None
            self.last_error = None
            self.safe_to_unload = False
            self.preparing_unload = False
            self.video_frames = 0
            self.audio_packets = 0
            self.video_codec = None
            self.latest_jpeg = None
            self.audio_enabled = False
            self.audio_queue.clear()
            self.thread = threading.Thread(target=self._run, name='stream360-receiver', daemon=True)
            self.thread.start()
        return self.status()

    def prepare_unload(self):
        with self.lock:
            if self.client is None:
                raise ValueError('Connect the Stream360 module before preparing unload.')
            if self.safe_to_unload:
                return self.status_unlocked()
            try:
                self.client.sendall(b'X')
            except OSError:
                raise ValueError('Stream360 prepare-unload command failed.') from None
            self.preparing_unload = True
            return self.status_unlocked()

    def status_unlocked(self):
        return {'state':self.state, 'port':self.port, 'connected':self.client is not None,
                'waiting_seconds':self.waiting_seconds_unlocked(),
                'video_frames':self.video_frames, 'audio_packets':self.audio_packets,
                'last_status':self.last_status, 'last_error':self.last_error,
                'safe_to_unload':self.safe_to_unload,
                'preparing_unload':self.preparing_unload,
                'video_codec':self.video_codec,
                'browser_frame_available':self.latest_jpeg is not None,
                'audio_enabled':self.audio_enabled}

    def stop(self, force=False):
        with self.lock:
            if self.listener is None:
                return self.status_unlocked()
            if self.client is not None and not self.safe_to_unload and not force:
                raise ValueError('Prepare unload and wait for SAFE_TO_UNLOAD before stopping the receiver.')
            self.stop_event.set()
            listener,client,thread = self.listener,self.client,self.thread
            self.listener = None
            self.client = None
            self.state = 'stopped'
            self.listening_since = None
            self.port = None
            self.latest_jpeg = None
            self.audio_enabled = False
            self.audio_queue.clear()
            self.safe_to_unload = False
            self.preparing_unload = False
        for sock in (client,listener):
            if sock is not None:
                try:sock.close()
                except OSError:pass
        if thread is not None and thread is not threading.current_thread():thread.join(timeout=2)
        return self.status()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                with self.lock:listener = self.listener
                if listener is None:break
                client,peer = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if peer[0] != self.expected_ip:
                client.close()
                continue
            client.settimeout(0.5)
            with self.lock:
                if self.stop_event.is_set():client.close();break
                self.client = client
                self.state = 'connected'
                self.listening_since = None
                self.safe_to_unload = False
                self.preparing_unload = False
                self.last_status = None
                self.last_error = None
                self.video_codec = None
                self.latest_jpeg = None
                self.audio_queue.clear()
            try:
                with self.lock:
                    client.sendall(INITIAL_CONTROL.replace(b'K',b'J') if self.audio_enabled else INITIAL_CONTROL)
                self._receive(client)
            except (OSError,ValueError,EOFError):
                with self.lock:
                    if not self.stop_event.is_set() and not self.safe_to_unload and self.last_error is None:
                        self.last_error = 'connection-closed'
            finally:
                try:client.close()
                except OSError:pass
                with self.lock:
                    if self.client is client:
                        self.client = None
                        self.latest_jpeg = None
                        self.audio_queue.clear()
                        # The vendor closes the stream after SAFE_TO_UNLOAD.
                        # Keep that acknowledgement until unload, stop, or a new peer.
                        self.preparing_unload = False
                        if not self.stop_event.is_set():
                            self.state = 'listening'
                            self.listening_since = time.monotonic()

    def _read(self, client, count):
        chunks = bytearray()
        while len(chunks) < count and not self.stop_event.is_set():
            try:chunk = client.recv(count-len(chunks))
            except socket.timeout:continue
            if not chunk:raise EOFError()
            chunks.extend(chunk)
        if len(chunks) != count:raise EOFError()
        return bytes(chunks)

    def _receive(self, client):
        while not self.stop_event.is_set():
            magic,codec,mode,width,height,quality,length,frame_no,capture_us,encode_us = HEADER.unpack(self._read(client,HEADER.size))
            if magic != MAGIC or length > MAX_PAYLOAD or codec not in (0,1,2,3):
                with self.lock:self.last_error = 'invalid-packet'
                raise ValueError('Invalid Stream360 packet.')
            payload = self._read(client,length)
            if codec == 0:
                message = payload.decode('ascii','replace')
                if message in STATUSES:
                    with self.lock:
                        self.last_status = message
                        if message == 'SAFE_TO_UNLOAD':
                            self.safe_to_unload = True
                            self.preparing_unload = False
                continue
            if codec == 1:
                valid = (0 < width <= 1920 and 0 < height <= 1080 and
                         len(payload) >= 4 and payload[:2] == b'\xff\xd8' and payload[-2:] == b'\xff\xd9')
            elif codec == 2:
                valid = (0 < width <= 1920 and 0 < height <= 1080 and
                         width % 2 == 0 and height % 2 == 0 and length == width*height*3//2)
            else:
                valid = (width == 2 and height in (8,16) and quality in (12000,24000,44100,48000)
                         and length > 0 and length % (2*(height//8)) == 0)
            if not valid:
                with self.lock:self.last_error = 'invalid-packet'
                raise ValueError('Invalid Stream360 media packet.')
            with self.lock:
                self.state = 'receiving'
                if codec == 3:
                    self.audio_packets += 1
                    if self.audio_enabled and length <= MAX_BROWSER_AUDIO:
                        self.audio_sequence += 1
                        self.audio_queue.append((self.audio_sequence,quality,height,payload))
                else:
                    self.video_frames += 1
                    self.video_codec = 'jpeg' if codec == 1 else 'i420'
                    if codec == 1 and length <= MAX_BROWSER_JPEG:
                        self.latest_jpeg = payload
                        self.frame_sequence += 1
                    else:
                        self.latest_jpeg = None
