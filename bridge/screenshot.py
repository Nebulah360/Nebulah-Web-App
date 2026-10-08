"""On-demand XBDM framebuffer capture. Pixels remain in memory and are never logged."""
import base64
import re
import struct
import zlib

from xbdm import line, session


MAX_FRAME = 16 * 1024 * 1024
SUPPORTED_FORMATS = {0x18280186, 0x182801B6}
FIELDS = ('pitch', 'width', 'height', 'format', 'offsetx', 'offsety',
          'framebuffersize', 'sw', 'sh', 'colorspace')


def parse_metadata(reply):
    try:
        text = reply.decode('ascii').strip().replace(',', ' ')
    except UnicodeError as error:
        raise ValueError('Screenshot metadata was malformed.') from error
    values = dict(re.findall(r'([a-z]+)=(0x[0-9a-fA-F]+|[0-9]+)', text))
    if set(values) != set(FIELDS):
        raise ValueError('Screenshot metadata was incomplete.')
    meta = {key: int(value, 0) for key, value in values.items()}
    width, height, pitch = meta['width'], meta['height'], meta['pitch']
    size = meta['framebuffersize']
    if (not 1 <= width <= 1920 or not 1 <= height <= 1080 or
            not width * 4 <= pitch <= 8192 or
            not pitch * height <= size <= MAX_FRAME or
            size > pitch * (height + 128) or
            meta['format'] & 0x7fffffff not in SUPPORTED_FORMATS or
            meta['offsetx'] or meta['offsety']):
        raise ValueError('Screenshot format or dimensions are unsupported.')
    return meta


def read_frame(stream, size):
    frame = bytearray(size)
    view = memoryview(frame)
    received = 0
    while received < size:
        count = stream.recv_into(view[received:])
        if not count:
            raise ValueError('Screenshot ended before the framebuffer was complete.')
        received += count
    return frame


def tiled_offset(x, y, width):
    aligned = (width + 31) & ~31
    macro = ((x >> 5) + (y >> 5) * (aligned >> 5)) << 9
    micro = ((x & 7) + ((y & 6) << 2)) << 2
    offset = (macro + ((micro & ~15) << 1) + (micro & 15) +
              ((y & 8) << 5) + ((y & 1) << 4))
    return (((offset & ~511) << 3) + ((y & 16) << 7) +
            ((offset & 448) << 2) + ((((y & 8) >> 2) + (x >> 3)) & 3) * 64 +
            (offset & 63))


def png(frame, meta, tiled=False):
    width, height, pitch = meta['width'], meta['height'], meta['pitch']
    scanlines = bytearray((width * 3 + 1) * height)
    for y in range(height):
        dest = y * (width * 3 + 1) + 1
        for x in range(width):
            source = tiled_offset(x, y, width) if tiled else y * pitch + x * 4
            if source + 4 > len(frame):
                raise ValueError('Screenshot framebuffer was incomplete.')
            scanlines[dest:dest+3] = frame[source+2], frame[source+1], frame[source]
            dest += 3
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(scanlines, 6)) + chunk(b'IEND', b''))


def capture(host):
    with session(host) as stream:
        stream.settimeout(15)
        stream.sendall(b'screenshot\r\n')
        if not line(stream).startswith(b'203-'):
            raise ValueError('XBDM screenshot command is unavailable.')
        meta = parse_metadata(line(stream, 1024))
        frame = read_frame(stream, meta['framebuffersize'])
    image = png(frame, meta, tiled=True)
    return {'png': base64.b64encode(image).decode('ascii'),
            'width': meta['width'], 'height': meta['height']}
