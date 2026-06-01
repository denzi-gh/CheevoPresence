import unittest

from pypresence import exceptions as pypresence_exceptions

from desktop.runtime.discord_gateway import DiscordPresenceGateway


class FakePresence:
    attempts = []
    failures = {}

    def __init__(self, client_id, pipe=None):
        self.client_id = client_id
        self.pipe = pipe
        self.closed = False
        self.cleared = False
        self.updated = None
        self.attempts.append(pipe)

    def connect(self):
        failure = self.failures.get(self.pipe)
        if failure:
            raise failure

    def update(self, **kwargs):
        self.updated = kwargs

    def clear(self):
        self.cleared = True

    def close(self):
        self.closed = True


class DiscordPresenceGatewayTests(unittest.TestCase):
    def setUp(self):
        FakePresence.attempts = []
        FakePresence.failures = {}
        self.statuses = []

    def _gateway(self):
        return DiscordPresenceGateway(
            presence_factory=FakePresence,
            status_callback=lambda status, text: self.statuses.append((status, text)),
        )

    def test_connect_falls_back_to_next_pipe(self):
        FakePresence.failures = {0: pypresence_exceptions.InvalidPipe()}
        gateway = self._gateway()

        self.assertTrue(gateway.connect())

        self.assertEqual([0, 1], FakePresence.attempts)
        self.assertEqual(1, gateway.rpc_pipe)
        self.assertTrue(gateway.rpc_connected)
        self.assertEqual(("connected", "Connected to Discord"), self.statuses[-1])

    def test_invalid_client_id_stops_retrying(self):
        FakePresence.failures = {0: pypresence_exceptions.InvalidID()}
        gateway = self._gateway()

        self.assertFalse(gateway.connect())

        self.assertEqual([0], FakePresence.attempts)
        self.assertFalse(gateway.rpc_connected)
        self.assertEqual(("error", "Discord connection failed"), self.statuses[-1])

    def test_update_and_disconnect_delegate_to_presence(self):
        gateway = self._gateway()
        self.assertTrue(gateway.connect())

        gateway.update(details="hello")
        self.assertEqual({"details": "hello"}, gateway.rpc.updated)
        presence = gateway.rpc

        gateway.disconnect()

        self.assertTrue(presence.cleared)
        self.assertTrue(presence.closed)
        self.assertIsNone(gateway.rpc)
        self.assertFalse(gateway.rpc_connected)


if __name__ == "__main__":
    unittest.main()
