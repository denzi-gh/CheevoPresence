import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import requests

from desktop.core.ra_client import APIResponseError, RAClient
from desktop.core.ra_models import PlayerGameActivity, UserActivity


class FakeResponse:
    def __init__(self, payload, error=None, json_error=None):
        self.payload = payload
        self.error = error
        self.json_error = json_error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(
            {"url": url, "params": params, "headers": headers, "timeout": timeout}
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _activity_payload():
    return {
        "data": {
            "type": "users",
            "id": "01JUSEREXAMPLE",
            "attributes": {
                "richPresence": "Playing Level 1",
                "richPresenceUpdatedAt": "2026-09-24T10:30:00.123456Z",
                "visibleRole": "code-reviewer",
                "displayableRoles": ["developer", "code-reviewer"],
            },
            "relationships": {"lastGame": {"data": {"type": "games", "id": "123"}}},
        },
        "included": [
            {"type": "games", "id": "123", "attributes": {"title": "~Hack~ Mega Game"}},
        ],
    }


def _player_game(game_id="123", resource_id="9001"):
    return {
        "type": "player-games",
        "id": resource_id,
        "attributes": {
            "lastUnlockAt": "2026-09-24T12:30:00+02:00",
            "lastUnlockHardcoreAt": "2026-09-24T10:00:00Z",
        },
        "relationships": {"game": {"data": {"type": "games", "id": game_id}}},
    }


class RAClientTests(unittest.TestCase):
    def test_get_user_profile_uses_the_v1_profile_endpoint(self):
        session = FakeSession(FakeResponse({"Permissions": 5}))
        client = RAClient(session=session, base_url="https://example.test/API/")

        self.assertEqual({"Permissions": 5}, client.get_user_profile("user", "key"))

        self.assertEqual(1, len(session.calls))
        self.assertEqual("https://example.test/API/API_GetUserProfile.php", session.calls[0]["url"])
        self.assertEqual({"u": "user", "y": "key"}, session.calls[0]["params"])

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

    def test_get_game_info_and_user_progress_uses_expected_endpoint(self):
        session = FakeSession(FakeResponse({}))
        client = RAClient(session=session)

        client.get_game_info_and_user_progress("user", "key", 668)

        self.assertTrue(
            session.calls[0]["url"].endswith("/API_GetGameInfoAndUserProgress.php")
        )
        self.assertEqual({"u": "user", "y": "key", "g": 668}, session.calls[0]["params"])

    def test_get_user_profile_v2_uses_api_host_header_and_parses_visible_role(self):
        session = FakeSession(
            FakeResponse(
                {
                    "data": {
                        "attributes": {
                            "visibleRole": "code-reviewer",
                            "displayableRoles": ["developer", "code-reviewer"],
                        }
                    }
                }
            )
        )
        client = RAClient(
            session=session,
            v2_base_url="https://api.example.test/v2/",
        )

        result = client.get_user_profile_v2("Some User", "key")

        self.assertEqual("code-reviewer", result["visibleRole"])
        call = session.calls[0]
        self.assertEqual("https://api.example.test/v2/users/Some%20User", call["url"])
        self.assertEqual({"fields[users]": "visibleRole,displayableRoles"}, call["params"])
        self.assertEqual("key", call["headers"]["X-API-Key"])
        self.assertEqual("application/vnd.api+json", call["headers"]["Accept"])
        self.assertEqual(10, call["timeout"])

    def test_rejects_non_dict_payload(self):
        client = RAClient(session=FakeSession(FakeResponse([])))

        with self.assertRaises(APIResponseError):
            client.get_user_progress("user", "key", 123)

    def test_get_user_profile_v2_rejects_malformed_payload(self):
        client = RAClient(session=FakeSession(FakeResponse({"data": []})))

        with self.assertRaises(APIResponseError):
            client.get_user_profile_v2("user", "key")

    def test_http_errors_propagate(self):
        error = requests.HTTPError("nope")
        client = RAClient(session=FakeSession(FakeResponse({}, error=error)))

        with self.assertRaises(requests.HTTPError):
            client.get_game("user", "key", 123)


class UserActivityTests(unittest.TestCase):
    def _fetch(self, payload):
        return RAClient(session=FakeSession(FakeResponse(payload))).get_user_activity("user", "key")

    def test_request_uses_wes_sparse_fieldset_and_header_authentication(self):
        session = FakeSession(FakeResponse(_activity_payload()))
        client = RAClient(session=session, v2_base_url="https://api.example.test/v2/")

        activity = client.get_user_activity(" Some User/Ü? ", "secret-key")

        self.assertEqual(1, len(session.calls))
        self.assertEqual({
            "url": "https://api.example.test/v2/users/Some%20User%2F%C3%9C%3F",
            "params": {
                "fields[users]": "richPresence,richPresenceUpdatedAt,visibleRole,displayableRoles",
                "include": "lastGame",
                "fields[games]": "title",
            },
            "headers": {"X-API-Key": "secret-key", "Accept": "application/vnd.api+json"},
            "timeout": 10,
        }, session.calls[0])
        self.assertEqual(UserActivity(
            game_id=123,
            game_title="~Hack~ Mega Game",
            rich_presence="Playing Level 1",
            rich_presence_updated_at=datetime(2026, 9, 24, 10, 30, 0, 123456, tzinfo=timezone.utc),
            visible_role="code-reviewer",
            displayable_roles=("developer", "code-reviewer"),
        ), activity)

    def test_timestamps_normalize_offsets_and_fractional_seconds_to_utc(self):
        for timestamp in (
            "2026-09-24T10:30:00.123456Z",
            "2026-09-24T10:30:00.123456+00:00",
            "2026-09-24T12:30:00.123456+02:00",
            "2026-09-24T05:00:00.123456-05:30",
        ):
            with self.subTest(timestamp=timestamp):
                payload = _activity_payload()
                payload["data"]["attributes"]["richPresenceUpdatedAt"] = timestamp
                self.assertEqual(
                    datetime(2026, 9, 24, 10, 30, 0, 123456, tzinfo=timezone.utc),
                    self._fetch(payload).rich_presence_updated_at,
                )

    def test_null_activity_and_last_game_represent_a_user_who_has_not_played(self):
        payload = _activity_payload()
        payload["data"]["attributes"].update(richPresence=None, richPresenceUpdatedAt=None)
        payload["data"]["relationships"]["lastGame"]["data"] = None
        payload["included"] = []

        activity = self._fetch(payload)

        self.assertIsNone(activity.game_id)
        self.assertIsNone(activity.game_title)
        self.assertIsNone(activity.rich_presence_updated_at)
        self.assertEqual("", activity.rich_presence)

    def test_last_game_is_matched_by_type_and_id_instead_of_included_order(self):
        payload = _activity_payload()
        payload["included"].insert(0, {"type": "games", "id": "456", "attributes": {"title": "Other"}})
        payload["included"].insert(0, {"type": "systems", "id": "123", "attributes": {"name": "NES"}})

        activity = self._fetch(payload)

        self.assertEqual(123, activity.game_id)
        self.assertEqual("~Hack~ Mega Game", activity.game_title)

    def test_sparse_response_can_omit_the_last_game_linkage(self):
        for included, expected in ((_activity_payload()["included"], 123), ([], None)):
            with self.subTest(expected_game_id=expected):
                payload = _activity_payload()
                del payload["data"]["relationships"]
                payload["included"] = included
                self.assertEqual(expected, self._fetch(payload).game_id)

    def test_snapshots_preserve_independent_text_timestamp_and_title_changes(self):
        payload = _activity_payload()
        session = FakeSession(FakeResponse(payload))
        client = RAClient(session=session)
        first = client.get_user_activity("user", "key")

        payload["data"]["attributes"]["richPresenceUpdatedAt"] = "2026-09-24T10:32:00Z"
        ping = client.get_user_activity("user", "key")
        self.assertEqual(first.rich_presence, ping.rich_presence)
        self.assertNotEqual(first.rich_presence_updated_at, ping.rich_presence_updated_at)

        payload["data"]["attributes"]["richPresence"] = "Playing Level 2"
        text_change = client.get_user_activity("user", "key")
        self.assertEqual(ping.rich_presence_updated_at, text_change.rich_presence_updated_at)
        self.assertEqual("Playing Level 2", text_change.rich_presence)

        payload["included"][0]["attributes"]["title"] = "~Homebrew~ Renamed Game"
        title_change = client.get_user_activity("user", "key")
        self.assertEqual(first.game_id, title_change.game_id)
        self.assertEqual("~Homebrew~ Renamed Game", title_change.game_title)
        self.assertEqual("~Hack~ Mega Game", first.game_title)
        self.assertEqual(4, len(session.calls))

    def test_roles_keep_unknown_slugs_and_distinguish_empty_from_unavailable(self):
        for roles, expected in (([], ()), (None, None), (["new-role", "developer"], ("new-role", "developer"))):
            with self.subTest(roles=roles):
                payload = _activity_payload()
                payload["data"]["attributes"].update(visibleRole=None, displayableRoles=roles)
                activity = self._fetch(payload)
                self.assertIsNone(activity.visible_role)
                self.assertEqual(expected, activity.displayable_roles)
        payload = _activity_payload()
        del payload["data"]["attributes"]["visibleRole"]
        del payload["data"]["attributes"]["displayableRoles"]
        self.assertIsNone(self._fetch(payload).displayable_roles)

    def test_snapshot_is_immutable_and_does_not_share_role_lists(self):
        payload = _activity_payload()
        activity = self._fetch(payload)
        payload["data"]["attributes"]["displayableRoles"].clear()

        self.assertEqual(("developer", "code-reviewer"), activity.displayable_roles)
        with self.assertRaises(FrozenInstanceError):
            activity.game_id = 456

    def test_rejects_malformed_documents_and_user_resources(self):
        for payload in (
            None, [], {}, {"errors": [{"status": "401"}]}, {"data": None}, {"data": []},
            {"data": {"type": "games", "id": "123", "attributes": {}}},
            {"data": {"type": "users", "attributes": {}}},
            {"data": {"type": "users", "id": "123", "attributes": []}},
            {**_activity_payload(), "errors": []},
        ):
            with self.subTest(payload=payload), self.assertRaises(APIResponseError):
                self._fetch(payload)

    def test_rejects_invalid_activity_fields_and_naive_timestamps(self):
        invalid_fields = {
            "richPresence": [123, [], {}],
            "richPresenceUpdatedAt": [123, "", "bad", "2026-09-24", "2026-09-24T10:30:00", "2026-02-30T10:30:00Z"],
            "visibleRole": [123, [], {}],
            "displayableRoles": ["developer", {}, [None], [123]],
        }
        for field, values in invalid_fields.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(APIResponseError):
                    payload = _activity_payload()
                    payload["data"]["attributes"][field] = value
                    self._fetch(payload)
        for field in ("richPresence", "richPresenceUpdatedAt"):
            with self.subTest(missing=field), self.assertRaises(APIResponseError):
                payload = _activity_payload()
                del payload["data"]["attributes"][field]
                self._fetch(payload)

    def test_rejects_invalid_last_game_linkage(self):
        for relationship in (
            None, [], {}, {"data": []}, {"data": {"type": "users", "id": "123"}},
            *({"data": {"type": "games", "id": value}} for value in (None, True, 123, "", "0", "-1", "abc", "1.5")),
        ):
            with self.subTest(relationship=relationship), self.assertRaises(APIResponseError):
                payload = _activity_payload()
                payload["data"]["relationships"]["lastGame"] = relationship
                self._fetch(payload)

    def test_rejects_missing_conflicting_or_malformed_included_game(self):
        for included in (None, {}, [], [None], [{"type": "games", "id": "456"}],
                         [{"type": "games", "id": "123", "attributes": {}}],
                         [{"type": "games", "id": "123", "attributes": {"title": None}}]):
            with self.subTest(included=included), self.assertRaises(APIResponseError):
                payload = _activity_payload()
                payload["included"] = included
                self._fetch(payload)
        payload = _activity_payload()
        payload["data"]["relationships"]["lastGame"]["data"] = None
        with self.assertRaises(APIResponseError):
            self._fetch(payload)
        payload = _activity_payload()
        payload["included"].append(deepcopy(payload["included"][0]))
        with self.assertRaises(APIResponseError):
            self._fetch(payload)

    def test_rejects_missing_or_ambiguous_game_in_sparse_response(self):
        payload = _activity_payload()
        del payload["data"]["relationships"]
        payload["included"].append({"type": "games", "id": "456", "attributes": {"title": "Other"}})
        with self.assertRaises(APIResponseError):
            self._fetch(payload)
        payload["included"] = [{"type": "systems", "id": "123"}]
        with self.assertRaises(APIResponseError):
            self._fetch(payload)
        del payload["included"]
        with self.assertRaises(APIResponseError):
            self._fetch(payload)


class PlayerGameActivityTests(unittest.TestCase):
    def _fetch(self, payload):
        return RAClient(session=FakeSession(FakeResponse(payload))).get_player_games_v2("user", "key")

    def test_recent_mode_evidence_request_is_bounded_and_omits_game_attributes(self):
        session = FakeSession(FakeResponse({"data": [_player_game()]}))
        client = RAClient(session=session, v2_base_url="https://api.example.test/v2/")

        activities = client.get_player_games_v2(" Some User/ ", "key")

        self.assertEqual((PlayerGameActivity(
            game_id=123,
            last_unlock_at=datetime(2026, 9, 24, 10, 30, tzinfo=timezone.utc),
            last_unlock_hardcore_at=datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc),
        ),), activities)
        self.assertEqual(1, len(session.calls))
        self.assertEqual({
            "url": "https://api.example.test/v2/users/Some%20User%2F/player-games",
            "params": {
                "fields[player-games]": "lastUnlockAt,lastUnlockHardcoreAt,game",
                "include": "game",
                "fields[games]": "",
                "sort": "-lastPlayedAt",
                "page[number]": 1,
                "page[size]": 10,
            },
            "headers": {"X-API-Key": "key", "Accept": "application/vnd.api+json"},
            "timeout": 10,
        }, session.calls[0])

    def test_targeted_lookup_can_fetch_the_active_game_outside_the_recent_page(self):
        session = FakeSession(FakeResponse({"data": [_player_game("456")]}))
        client = RAClient(session=session)

        activities = client.get_player_games_v2("user", "key", game_id=456, limit=1)

        self.assertEqual(456, activities[0].game_id)
        self.assertEqual(456, session.calls[0]["params"]["filter[gameId]"])
        self.assertEqual(1, session.calls[0]["params"]["page[size]"])
        self.assertEqual(1, len(session.calls))

    def test_game_association_uses_relationships_without_included_games(self):
        activities = self._fetch({"data": [_player_game("123", "9001"), _player_game("456", "9002")]})

        self.assertEqual([123, 456], [activity.game_id for activity in activities])

    def test_empty_collection_and_null_unlock_history_are_valid(self):
        self.assertEqual((), self._fetch({"data": []}))
        item = _player_game()
        item["attributes"] = {"lastUnlockAt": None, "lastUnlockHardcoreAt": None}
        self.assertEqual((PlayerGameActivity(123, None, None),), self._fetch({"data": [item]}))

    def test_does_not_follow_pagination_links(self):
        session = FakeSession(FakeResponse({"data": [], "links": {"next": "https://api.example.test/next"}}))
        RAClient(session=session).get_player_games_v2("user", "key")
        self.assertEqual(1, len(session.calls))

    def test_rejects_malformed_collections_and_entries(self):
        for payload in ({}, {"data": None}, {"data": {}}, {"data": [None]}, {"data": [{}]}):
            with self.subTest(payload=payload), self.assertRaises(APIResponseError):
                self._fetch(payload)
        for key, value in (("type", "games"), ("id", None), ("attributes", None), ("relationships", {})):
            with self.subTest(key=key), self.assertRaises(APIResponseError):
                item = _player_game()
                item[key] = value
                self._fetch({"data": [item]})
        for field in ("lastUnlockAt", "lastUnlockHardcoreAt"):
            for attributes in ({}, {field: "bad"}):
                with self.subTest(field=field, attributes=attributes), self.assertRaises(APIResponseError):
                    item = _player_game()
                    item["attributes"].pop(field)
                    item["attributes"].update(attributes)
                    self._fetch({"data": [item]})


class RAClientFailureTests(unittest.TestCase):
    METHODS = (
        ("get_user_activity", ()),
        ("get_player_games_v2", ()),
        ("get_user_profile", ()),
        ("get_game_info_and_user_progress", (123,)),
    )

    def test_http_failures_propagate_without_parsing_or_follow_up_requests(self):
        for status in (401, 403, 404, 429, 500, 503):
            for method, args in self.METHODS:
                with self.subTest(status=status, method=method):
                    response = requests.Response()
                    response.status_code = status
                    error = requests.HTTPError(response=response)
                    session = FakeSession(FakeResponse({}, error=error, json_error=AssertionError("must not parse")))
                    with self.assertRaises(requests.HTTPError) as caught:
                        getattr(RAClient(session=session), method)("user", "key", *args)
                    self.assertIs(error, caught.exception)
                    self.assertEqual(1, len(session.calls))

    def test_transport_failures_propagate_without_retry_or_fallback(self):
        for error in (requests.Timeout("timeout"), requests.ConnectionError("offline")):
            for method, args in self.METHODS:
                with self.subTest(error=type(error), method=method):
                    session = FakeSession(error)
                    with self.assertRaises(type(error)) as caught:
                        getattr(RAClient(session=session), method)("user", "key", *args)
                    self.assertIs(error, caught.exception)
                    self.assertEqual(1, len(session.calls))

    def test_invalid_json_becomes_a_safe_response_error_without_fallback(self):
        for method, args in self.METHODS:
            with self.subTest(method=method):
                session = FakeSession(FakeResponse(None, json_error=ValueError("untrusted-body-with-secret")))
                with self.assertRaises(APIResponseError) as caught:
                    getattr(RAClient(session=session), method)("user", "key", *args)
                self.assertNotIn("untrusted-body", str(caught.exception))
                self.assertEqual(1, len(session.calls))


if __name__ == "__main__":
    unittest.main()
