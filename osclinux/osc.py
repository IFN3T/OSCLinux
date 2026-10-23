"""Minimal OSC 1.0 sender and VRChat status listener."""

from __future__ import annotations

import socket
import struct
import threading
import time


def _osc_string(value: str) -> bytes:
    encoded = value.encode("utf-8") + b"\0"
    return encoded + b"\0" * ((-len(encoded)) % 4)


def encode_message(address: str, *arguments: str | bool | int | float) -> bytes:
    tags = [","]
    payload = bytearray()
    for value in arguments:
        if isinstance(value, bool):
            tags.append("T" if value else "F")
        elif isinstance(value, str):
            tags.append("s")
            payload.extend(_osc_string(value))
        elif isinstance(value, int):
            tags.append("i")
            payload.extend(struct.pack(">i", value))
        elif isinstance(value, float):
            tags.append("f")
            payload.extend(struct.pack(">f", value))
        else:
            raise TypeError(f"Type OSC non pris en charge : {type(value).__name__}")
    return _osc_string(address) + _osc_string("".join(tags)) + bytes(payload)


class OscClient:
    def __init__(self) -> None:
        self._socket: socket.socket | None = None

    def send_chatbox(self, text: str, host: str, port: int, *, send_now: bool = True, notification: bool = False) -> None:
        message = text[:144]
        if self._socket is None:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.sendto(encode_message("/chatbox/input", message, send_now, notification), (host, port))

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None


class VRChatListener:
    def __init__(self, port: int, callback) -> None:
        self.port = port
        self.callback = callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None

    def start(self) -> None:
        def listen() -> None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.settimeout(0.5)
                sock.bind(("0.0.0.0", self.port))
                while not self._stop.is_set():
                    try:
                        packet, _address = sock.recvfrom(65535)
                        if packet.startswith(b"/"):
                            self.callback(time.monotonic())
                    except socket.timeout:
                        continue
            except OSError as exc:
                self.error = str(exc)
            finally:
                sock.close()
        self._thread = threading.Thread(target=listen, name="vrchat-osc-listener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
