"""Bounded read-only XBDM transport and drive-list probe."""
import re
import socket


def line(stream, limit=4096):
    data = bytearray()
    while not data.endswith(b'\r\n'):
        part = stream.recv(1)
        if not part or len(data) >= limit:
            raise ValueError('XBDM reply was incomplete.')
        data.extend(part)
    return bytes(data)


def exact(stream, count):
    data = bytearray()
    while len(data) < count:
        part = stream.recv(count - len(data))
        if not part:
            raise ValueError('XBDM memory reply was incomplete.')
        data.extend(part)
    return bytes(data)


def session(host):
    if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,253}', host):
        raise ValueError('Console connection unavailable.')
    stream = socket.create_connection((host, 730), timeout=3)
    stream.settimeout(3)
    if not line(stream).startswith(b'201-'):
        stream.close()
        raise ValueError('XBDM did not accept the connection.')
    return stream


def drives(host):
    with session(host) as stream:
        stream.sendall(b'drivelist\r\n')
        if not line(stream).startswith(b'202-'):
            raise ValueError('XBDM drive list unavailable.')
        roots = []
        seen = set()
        for _ in range(64):
            reply = line(stream)
            if reply == b'.\r\n':
                return roots
            match = re.fullmatch(rb'drivename="([A-Za-z0-9_]{1,32})(?::\\?)?"\r\n', reply)
            if not match:
                raise ValueError('XBDM drive list was malformed.')
            root = match[1].decode('ascii') + ':\\'
            if root.casefold() not in seen:
                seen.add(root.casefold())
                roots.append(root)
        raise ValueError('XBDM drive list was incomplete.')
