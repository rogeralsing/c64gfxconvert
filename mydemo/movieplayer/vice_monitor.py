"""VICE text-monitor transport shared by the native effects verifier."""

import re
import socket
import time

PROMPT = re.compile(rb"\((?:C|8|9|10|11):\$[0-9a-fA-F]{4}\) $")


class Monitor:
    def __init__(self, connection):
        self.connection, self.transcript = connection, []
        connection.settimeout(60)
        self.run("r")

    def run(self, command):
        self.connection.sendall((command + "\n").encode())
        response = bytearray()
        needs_registers = command.strip().lower() in ("r", "registers")
        while not PROMPT.search(response) or (needs_registers and not re.search(rb"^\.;", response, re.M)):
            chunk = self.connection.recv(65536)
            if not chunk:
                raise ConnectionError("Owned VICE monitor closed unexpectedly.")
            response.extend(chunk)
        text = response.decode(errors="replace")
        self.transcript.append(command + "\n" + text)
        if re.search(r"ERROR|Unknown command|Unknown resource|Syntax error", text):
            raise RuntimeError(f"VICE rejected {command!r}:\n{text}")
        return text

    def registers(self):
        response = self.run("r")
        match = re.search(r"^\.;([0-9a-fA-F]{4})\s+(.*)$", response, re.M)
        if not match:
            raise RuntimeError(f"Incomplete VICE registers response:\n{response}")
        fields = match[2].split()
        return {"pc": int(match[1], 16), "raster": int(fields[-3]),
                "raster_cycle": int(fields[-2]), "clock": int(fields[-1])}

    def checkpoint(self, address):
        response = self.run(f"break {address:04x}")
        match = re.search(r"BREAK:\s*(\d+)", response)
        if not match:
            raise RuntimeError(f"No breakpoint at ${address:04x}")
        return int(match[1])

    def dump(self, path, first, last):
        self.run(f'bsave "{path.resolve()}" 0 {first:04x} {last:04x}')
        data = path.read_bytes()
        if len(data) != last - first + 1:
            raise RuntimeError(f"Incomplete VICE dump: {path}")
        return data


def connect(process, port):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Owned VICE exited at startup; inspect vice.log.")
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=1)
        except OSError:
            time.sleep(.1)
    raise TimeoutError("Owned VICE monitor did not open in 15 seconds.")
