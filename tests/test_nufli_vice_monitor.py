"""Monitor completion regressions; no VICE process or image fitting required."""

import importlib.util
from pathlib import Path
import socket
import threading
import time
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "nufli/verify-vice.py"
SPEC = importlib.util.spec_from_file_location("nufli_vice_verifier", SOURCE)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class MonitorResponseTests(unittest.TestCase):
    def test_waits_for_complete_prompt_across_socket_quiet_gap(self):
        body = b"Saving screenshot...\n"
        prompt = b"(C:$310d) "
        client, peer = socket.socketpair()
        with client, peer:
            client.settimeout(0.15)
            peer.sendall(body)

            def complete():
                time.sleep(0.25)
                peer.sendall(prompt[:7])
                time.sleep(0.02)
                peer.sendall(prompt[7:])

            writer = threading.Thread(target=complete)
            writer.start()
            try:
                response = VERIFIER.receive_monitor_response(client, timeout=2)
                self.assertEqual(response, (body + prompt).decode())
            finally:
                writer.join(timeout=2)

    def test_register_reply_does_not_complete_at_stale_initial_prompt(self):
        initial = b"(C:$fd75) "
        reply = b"  ADDR A X Y SP\n.;310d 00 00 00 f6\n(C:$310d) "
        client, peer = socket.socketpair()
        with client, peer:
            peer.sendall(initial)

            def complete():
                time.sleep(0.03)
                peer.sendall(reply)

            writer = threading.Thread(target=complete)
            writer.start()
            try:
                response = VERIFIER.receive_monitor_response(client, timeout=2, require_registers=True)
                self.assertEqual(response, (initial + reply).decode())
            finally:
                writer.join(timeout=2)

    def test_eof_before_prompt_is_reported(self):
        client, peer = socket.socketpair()
        with client, peer:
            peer.sendall(b"Incomplete response\n")
            peer.shutdown(socket.SHUT_WR)
            with self.assertRaisesRegex(ConnectionError, "closed.*prompt"):
                VERIFIER.receive_monitor_response(client, timeout=2)

    def test_deadline_is_total_even_when_partial_data_keeps_arriving(self):
        class BusySocket:
            now = 0

            def settimeout(self, timeout):
                pass

            def recv(self, size):
                self.now += 0.04
                return b"Still working\n" if self.now < 0.4 else b""

        monitor = BusySocket()
        with mock.patch.object(VERIFIER.time, "monotonic", side_effect=lambda: monitor.now):
            with self.assertRaisesRegex(TimeoutError, "prompt"):
                VERIFIER.receive_monitor_response(monitor, timeout=0.1)


if __name__ == "__main__":
    unittest.main()
