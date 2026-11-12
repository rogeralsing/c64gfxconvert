#!/usr/bin/env python3
"""Shared VICE monitor helpers copied unchanged from c64demo/verify.py."""

import re
import socket
import time


PROMPT = re.compile(rb"\(C:\$[0-9a-fA-F]{4}\) $")


def read_labels(path):
    """Read the assembler's normal debug symbols; no special test build is needed."""
    return {name: int(address, 16) for name, address in
            re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}


class Monitor:
    def __init__(self, connection):
        self.connection = connection
        self.transcript = []
        # VICE may greet a new client before its first command. Consume that
        # unsolicited prompt so it cannot be mistaken for a command response.
        connection.settimeout(0.1)
        try:
            while connection.recv(65536):
                pass
        except socket.timeout:
            pass
        connection.settimeout(15)

    def run(self, command):
        self.connection.sendall((command + "\n").encode())
        response = b""
        while not PROMPT.search(response) or (command == "r" and not re.search(rb"^\.;", response, re.M)):
            part = self.connection.recv(65536)
            if not part:
                raise RuntimeError("VICE closed its monitor connection.")
            response += part
        text = response.decode(errors="replace")
        self.transcript.append(command + "\n" + text)
        if re.search(r"ERROR|Unknown command|Unknown resource|Syntax error", text):
            raise RuntimeError(f"VICE rejected {command!r}:\n{text}")
        return text

    def memory(self, path, first, last):
        self.run(f'bsave "{path.resolve()}" 0 {first:04x} {last:04x}')
        data = path.read_bytes()
        if len(data) != last - first + 1:
            raise RuntimeError("VICE wrote an incomplete memory dump.")
        return data

    def registers(self):
        response = self.run("r")
        match = re.search(r"^\.;([0-9a-fA-F]{4})\s+(.*)$", response, re.M)
        if not match:
            raise RuntimeError(f"Could not read VICE registers:\n{response}")
        fields = match[2].split()
        return int(match[1], 16), int(fields[-3]), int(fields[-1])


def vice_command(executable, program, port, palette):
    return [executable, "-default", "+saveres", "-minimized", "-pal",
            "-speed", "100", "+warp", "+autostart-warp", "+confirmonexit",
            "-sounddev", "dummy", "+refreshonbreak", "+binarymonitor",
            "-autostartprgmode", "1", "-autostart", str(program.resolve()),
            "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette),
            "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
            "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
            "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]


def connect_monitor(process, port):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("VICE exited during startup; inspect vice.log.")
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=1)
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("VICE did not open its remote monitor within 15 seconds.")
