"""Small, bounded loopback-only WebSocket peer for synthetic integration tests.

Not an application transport or a replacement for a WebSocket library. Supports
text/binary messages, continuation and ping/close frames without extensions.
"""

import base64
import hashlib
import os
import socket
import struct
from urllib.parse import urlsplit


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
LIMIT = 8 * 1024 * 1024


def accept_key(key):
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


class FixtureWebSocket:
    def __init__(self, reader, writer, *, masked):
        self.reader, self.writer, self.masked = reader, writer, masked

    def read_exact(self, length):
        result = bytearray()
        while len(result) < length:
            part = self.reader.read(length - len(result))
            if not part:
                raise EOFError("fixture socket closed")
            result.extend(part)
        return bytes(result)

    def send(self, payload, opcode=1):
        if len(payload) > LIMIT:
            raise ValueError("fixture frame exceeds limit")
        length = len(payload)
        marker = 0x80 if self.masked else 0
        header = bytes([0x80 | opcode])
        if length < 126:
            header += bytes([marker | length])
        elif length < 65536:
            header += bytes([marker | 126]) + struct.pack("!H", length)
        else:
            header += bytes([marker | 127]) + struct.pack("!Q", length)
        if self.masked:
            mask = os.urandom(4)
            header += mask
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.writer.write(header + payload)
        self.writer.flush()

    def receive(self):
        parts = bytearray()
        started = False
        while True:
            first, second = self.read_exact(2)
            if first & 0x70:
                raise ValueError("fixture peer does not support extensions")
            final, opcode, masked = bool(first & 0x80), first & 0x0F, bool(second & 0x80)
            if masked == self.masked:
                raise ValueError("invalid peer masking direction")
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self.read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self.read_exact(8))[0]
            if length > LIMIT or len(parts) + length > LIMIT:
                raise ValueError("fixture message exceeds limit")
            mask = self.read_exact(4) if masked else None
            payload = self.read_exact(length)
            if mask:
                payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
            if opcode in (8, 9, 10):
                if not final or length > 125:
                    raise ValueError("invalid fixture control frame")
                if opcode == 8:
                    self.send(payload, opcode=8)
                    return None
                if opcode == 9:
                    self.send(payload, opcode=10)
                continue
            if opcode in (1, 2):
                if started:
                    raise ValueError("unexpected fixture data frame")
                started = True
            elif opcode != 0 or not started:
                raise ValueError("invalid fixture continuation")
            parts.extend(payload)
            if final:
                return bytes(parts)


class LoopbackWebSocketClient(FixtureWebSocket):
    def __init__(self, url, key, *, headers=None):
        target = urlsplit(url)
        if target.scheme != "ws" or target.hostname != "127.0.0.1" or not target.port:
            raise ValueError("only loopback fixture WebSockets are allowed")
        self.socket = socket.create_connection((target.hostname, target.port), timeout=15)
        self.file = self.socket.makefile("rwb", buffering=0)
        nonce = base64.b64encode(os.urandom(16)).decode()
        extra_headers = "".join(f"{name}: {value}\r\n" for name, value in (headers or {}).items())
        request = (
            f"GET {target.path} HTTP/1.1\r\nHost: 127.0.0.1:{target.port}\r\n"
            "Connection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\n"
            f"Sec-WebSocket-Key: {nonce}\r\nAuthorization: Bearer {key}\r\n{extra_headers}\r\n"
        )
        try:
            self.file.write(request.encode())
            status = self.file.readline(8192)
            if b" 101 " not in status:
                raise RuntimeError(f"fixture WS upgrade failed: {status!r}")
            headers = {}
            for _ in range(100):
                line = self.file.readline(8192)
                if line == b"\r\n":
                    break
                if not line or b":" not in line:
                    raise RuntimeError("invalid fixture WS handshake")
                name, value = line.decode().split(":", 1)
                headers[name.lower()] = value.strip()
            else:
                raise RuntimeError("fixture WS handshake too large")
            if headers.get("sec-websocket-accept") != accept_key(nonce):
                raise RuntimeError("fixture WS handshake accept mismatch")
            super().__init__(self.file, self.file, masked=True)
        except BaseException:
            self.file.close()
            self.socket.close()
            raise

    def close(self):
        try:
            self.send(struct.pack("!H", 1000), opcode=8)
        except (OSError, ValueError):
            pass
        finally:
            self.file.close()
            self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
