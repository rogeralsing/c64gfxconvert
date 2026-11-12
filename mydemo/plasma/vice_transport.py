#!/usr/bin/env python3
"""Read-only VICE monitor and screenshot helpers retained from the ECM experiment."""

from pathlib import Path
import re
import socket
import time

from PIL import Image, ImageChops


OUTPUT = Path(__file__).resolve().parent / "build"
PROMPT = re.compile(rb"\((?:C|8|9|10|11):\$[0-9a-fA-F]{4}\) $")


class Monitor:
    def __init__(self, connection):
        self.connection = connection
        self.transcript = []
        connection.settimeout(30)
        self.run("r")

    def run(self, command):
        self.connection.sendall((command + "\n").encode())
        response = bytearray()
        while not PROMPT.search(response) or (
            command == "r" and not re.search(rb"^\.;", response, re.M)
        ):
            chunk = self.connection.recv(65536)
            if not chunk:
                raise ConnectionError("Owned VICE monitor closed unexpectedly.")
            response.extend(chunk)
        result = response.decode(errors="replace")
        self.transcript.append(command + "\n" + result)
        if re.search(r"ERROR|Unknown command|Unknown resource|Syntax error", result):
            raise RuntimeError(f"VICE rejected {command!r}: {result}")
        return result

    def dump(self, name, first, last):
        path = OUTPUT / name
        self.run(f'bsave "{path}" 0 {first:04x} {last:04x}')
        data = path.read_bytes()
        if len(data) != last - first + 1:
            raise AssertionError(f"Incomplete VICE memory dump: {path}")
        return data


def connect_monitor(process, port):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Owned VICE exited; inspect build/vice.log.")
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=1)
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("Owned VICE monitor did not start within 15 seconds.")


def compare_screenshot(path, expected):
    screenshot = Image.open(path).convert("RGB")
    for top in range(28, 49):
        for left in range(28, 41):
            crop = screenshot.crop((left, top, left + 320, top + 200))
            if ImageChops.difference(crop, expected).getbbox() is None:
                return {"origin": [left, top], "compared_pixels": 64000,
                        "mismatched_pixels": 0}
    raise AssertionError("Native VIC-II screenshot differs from independent ECM decoding.")
