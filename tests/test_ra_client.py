import unittest

import requests

from desktop.core.ra_client import APIResponseError, RAClient


class FakeResponse:
    def __init__(self, payload, error=None):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return self.response


class RAClientTests(unittest.TestCase):
    def test_get_user_summary_sends_expected_params(self):
        session = FakeSession(FakeResponse({"ok": True}))
        client = RAClient(session=session, base_url="https://example.test/API/")

        self.assertEqual({"ok": True}, client.get_user_summary("user", "key"))

        call = session.calls[0]
        self.assertEqual("https://example.test/API/API_GetUserSummary.php", call["url"])
        self.assertEqual("user", call["params"]["u"])
        self.assertEqual("key", call["params"]["y"])
        self.assertEqual(0, call["params"]["g"])
        self.assertEqual(0, call["params"]["a"])
        self.assertIn("noCache", call["params"])
        self.assertEqual(10, call["timeout"])

    def test_get_game_and_progress_use_expected_endpoints(self):
        session = FakeSession(FakeResponse({}))
        client = RAClient(session=session)

        client.get_game("user", "key", 123)
        client.get_user_progress("user", "key", 123)

        self.assertTrue(session.calls[0]["url"].endswith("/API_GetGame.php"))
        self.assertEqual({"z": "user", "y": "key", "i": 123}, session.calls[0]["params"])
        self.assertTrue(session.calls[1]["url"].endswith("/API_GetUserProgress.php"))
        self.assertEqual({"u": "user", "y": "key", "i": 123}, session.calls[1]["params"])

    def test_rejects_non_dict_payload(self):
        client = RAClient(session=FakeSession(FakeResponse([])))

        with self.assertRaises(APIResponseError):
            client.get_user_progress("user", "key", 123)

    def test_http_errors_propagate(self):
        error = requests.HTTPError("nope")
        client = RAClient(session=FakeSession(FakeResponse({}, error=error)))

        with self.assertRaises(requests.HTTPError):
            client.get_game("user", "key", 123)


if __name__ == "__main__":
    unittest.main()
