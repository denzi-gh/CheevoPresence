import unittest

from pypresence import exceptions as pypresence_exceptions

from desktop.runtime.worker import RPCWorker


class FakePresence:
    attempts = []
    failures = {}
    instances = []

    def __init__(self, client_id, pipe=None):
        self.client_id = client_id
        self.pipe = pipe
        self.closed = False
        self.instances.append(self)
        self.attempts.append(pipe)

    def connect(self):
        failure = self.failures.get(self.pipe)
        if failure:
            raise failure

    def close(self):
        self.closed = True

    def clear(self):
        pass


class DiscordIpcPipeTests(unittest.TestCase):
    def setUp(self):
        FakePresence.attempts = []
        FakePresence.failures = {}
        FakePresence.instances = []

    def _make_worker(self):
        return RPCWorker(
            initial_config={},
            console_icons={},
            presence_factory=FakePresence,
        )

    def test_connect_falls_back_to_next_pipe(self):
        FakePresence.failures = {
            0: pypresence_exceptions.InvalidPipe(),
        }
        worker = self._make_worker()

        with self.assertLogs("desktop.runtime.worker", level="INFO") as logs:
            self.assertTrue(worker._connect_rpc())

        self.assertEqual([0, 1], FakePresence.attempts)
        self.assertTrue(FakePresence.instances[0].closed)
        self.assertIs(worker.rpc, FakePresence.instances[1])
        self.assertEqual(1, worker.rpc_pipe)
        self.assertTrue(worker.rpc_connected)
        self.assertEqual("connected", worker.current_status)
        output = "\n".join(logs.output)
        self.assertIn("Discord IPC connect attempt pipe=0", output)
        self.assertIn("Discord IPC pipe unavailable pipe=0", output)
        self.assertIn("Discord IPC connected pipe=1", output)

    def test_connect_prefers_last_working_pipe(self):
        worker = self._make_worker()
        worker.rpc_pipe = 3

        self.assertTrue(worker._connect_rpc())

        self.assertEqual([3], FakePresence.attempts)
        self.assertEqual(3, worker.rpc_pipe)

    def test_connect_continues_after_stale_cached_pipe(self):
        FakePresence.failures = {
            3: pypresence_exceptions.InvalidPipe(),
            0: pypresence_exceptions.InvalidPipe(),
            1: pypresence_exceptions.InvalidPipe(),
        }
        worker = self._make_worker()
        worker.rpc_pipe = 3

        self.assertTrue(worker._connect_rpc())

        self.assertEqual([3, 0, 1, 2], FakePresence.attempts)
        self.assertEqual(2, worker.rpc_pipe)

    def test_connect_reports_discord_unavailable_after_all_pipes_fail(self):
        FakePresence.failures = {
            pipe: pypresence_exceptions.InvalidPipe()
            for pipe in range(10)
        }
        worker = self._make_worker()

        self.assertFalse(worker._connect_rpc())

        self.assertEqual(list(range(10)), FakePresence.attempts)
        self.assertIsNone(worker.rpc)
        self.assertIsNone(worker.rpc_pipe)
        self.assertFalse(worker.rpc_connected)
        self.assertEqual("error", worker.current_status)
        self.assertEqual("Discord is not open", worker.status_text)

    def test_connect_does_not_retry_invalid_client_id(self):
        FakePresence.failures = {
            0: pypresence_exceptions.InvalidID(),
        }
        worker = self._make_worker()

        self.assertFalse(worker._connect_rpc())

        self.assertEqual([0], FakePresence.attempts)
        self.assertIsNone(worker.rpc)
        self.assertFalse(worker.rpc_connected)
        self.assertEqual("error", worker.current_status)
        self.assertEqual("Discord connection failed", worker.status_text)


if __name__ == "__main__":
    unittest.main()
