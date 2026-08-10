"""Tests for the IPC framing helper _read_message.

Covers the _MAX_MESSAGE_BYTES guard (a client must not be able to make the
host buffer an unbounded message) alongside the empty and happy paths.
"""

import json
import unittest

from desktop.shell.ipc import _MAX_MESSAGE_BYTES, _read_message


class FakeConn:
    """A socket-like object whose recv() replays queued chunks."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def recv(self, _bufsize):
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class ReadMessageTests(unittest.TestCase):
    def test_parses_newline_terminated_json(self):
        payload = {"method": "get_state", "token": "t"}
        conn = FakeConn([json.dumps(payload).encode("utf-8") + b"\n"])

        self.assertEqual(payload, _read_message(conn))

    def test_stops_at_first_newline(self):
        conn = FakeConn([b'{"method":"a"}\n{"method":"b"}\n'])

        self.assertEqual({"method": "a"}, _read_message(conn))

    def test_empty_message_is_rejected(self):
        conn = FakeConn([b""])

        with self.assertRaises(RuntimeError) as ctx:
            _read_message(conn)
        self.assertIn("Empty", str(ctx.exception))

    def test_oversized_message_is_rejected(self):
        # A stream that never sends a newline and exceeds the cap must not be
        # buffered without bound.
        chunk = b"x" * 4096
        chunk_count = (_MAX_MESSAGE_BYTES // len(chunk)) + 2
        conn = FakeConn([chunk] * chunk_count)

        with self.assertRaises(RuntimeError) as ctx:
            _read_message(conn)
        self.assertIn("too large", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
