"""Tests for the worker's config ownership and gateway delegation.

WP16 made the gateway the single owner of the Discord connection state and
routed config swaps through a lock-guarded setter.
"""

import unittest

from desktop.runtime.worker import RPCWorker


class _FakeGateway:
    def __init__(self):
        self.rpc = "sentinel-rpc"
        self.rpc_connected = True
        self.rpc_pipe = 4
        self.start_time = 111
        self.presence_factory = None
        self.status_callback = None


def _worker(gateway=None):
    return RPCWorker(
        initial_config={"username": "u", "apikey": "k"},
        console_icons={},
        discord_gateway=gateway or _FakeGateway(),
    )


class GatewayOwnershipTests(unittest.TestCase):
    def test_connection_state_reads_delegate_to_gateway(self):
        gateway = _FakeGateway()
        worker = _worker(gateway)

        self.assertEqual("sentinel-rpc", worker.rpc)
        self.assertTrue(worker.rpc_connected)
        self.assertEqual(4, worker.rpc_pipe)
        self.assertEqual(111, worker.start_time)

    def test_writable_delegates_go_back_to_gateway(self):
        gateway = _FakeGateway()
        worker = _worker(gateway)

        worker.rpc_pipe = 7
        worker.start_time = 222

        # No shadow copy on the worker: the gateway is the single owner.
        self.assertEqual(7, gateway.rpc_pipe)
        self.assertEqual(222, gateway.start_time)
        self.assertNotIn("rpc_pipe", worker.__dict__)
        self.assertNotIn("start_time", worker.__dict__)


class ReplaceConfigTests(unittest.TestCase):
    def test_replace_config_normalizes_and_swaps(self):
        worker = _worker()

        worker.replace_config({"username": "new", "apikey": "key"})

        self.assertEqual("new", worker.config["username"])
        # normalize_config fills defaults for omitted keys.
        self.assertIn("interval", worker.config)
        self.assertIn("dev_mode", worker.config)

    def test_config_snapshot_is_a_copy(self):
        worker = _worker()

        snapshot = worker._config_snapshot()
        snapshot["username"] = "mutated"

        self.assertNotEqual("mutated", worker.config["username"])


if __name__ == "__main__":
    unittest.main()
