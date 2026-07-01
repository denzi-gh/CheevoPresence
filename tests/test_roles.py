import unittest
from unittest.mock import patch

from desktop.core.roles import (
    DEBUG_FORCE_ROLE_PERMISSION_ENV,
    coerce_permissions,
    debug_forced_role_permission,
    is_elevated_permission,
    resolve_dev_mode,
    role_from_api,
    role_from_permissions,
    role_from_visible_role,
    roles_grant_dev_mode,
)
from desktop.shell.tk_widgets import role_badge_style


class RoleTests(unittest.TestCase):
    def test_maps_special_permissions_to_roles(self):
        cases = {
            2: ("Junior Developer", "junior_developer"),
            "3": ("Developer", "developer"),
            4: ("Moderator", "moderator"),
            5: ("Admin", "admin"),
            6: ("Admin", "admin"),
        }

        for permissions, expected in cases.items():
            with self.subTest(permissions=permissions):
                role = role_from_permissions(permissions)

                self.assertIsNotNone(role)
                self.assertEqual(expected[0], role.label)
                self.assertEqual(expected[1], role.tier)

    def test_normal_missing_malformed_and_banned_permissions_have_no_role(self):
        for permissions in (-2, -1, 0, 1, None, "", "nope"):
            with self.subTest(permissions=permissions):
                self.assertIsNone(role_from_permissions(permissions))

    def test_maps_supported_visible_roles_to_roles(self):
        cases = {
            "developer": ("Developer", "developer"),
            "developer-junior": ("Junior Developer", "junior_developer"),
            "event-manager": ("Event Manager", "event_manager"),
            "artist": ("Artist", "artist"),
            "play-tester": ("Play Tester", "play_tester"),
            "writer": ("Writer", "writer"),
            "moderator": ("Moderator", "moderator"),
            "code-reviewer": ("Code Reviewer", "code_reviewer"),
        }

        for slug, expected in cases.items():
            with self.subTest(slug=slug):
                role = role_from_visible_role(slug)

                self.assertIsNotNone(role)
                self.assertEqual(expected[0], role.label)
                self.assertEqual(expected[1], role.tier)

    def test_visible_role_accepts_underscore_and_case_variants(self):
        role = role_from_visible_role("Code_Reviewer")

        self.assertIsNotNone(role)
        self.assertEqual("Code Reviewer", role.label)
        self.assertEqual("code_reviewer", role.tier)

    def test_visible_role_accepts_tier_and_label_variants(self):
        cases = {
            "junior_developer": ("Junior Developer", "junior_developer"),
            "event_manager": ("Event Manager", "event_manager"),
            "Play Tester": ("Play Tester", "play_tester"),
        }

        for value, expected in cases.items():
            with self.subTest(value=value):
                role = role_from_visible_role(value)

                self.assertIsNotNone(role)
                self.assertEqual(expected[0], role.label)
                self.assertEqual(expected[1], role.tier)

    def test_role_from_api_prefers_supported_visible_role(self):
        role = role_from_api(3, visible_role="artist")

        self.assertIsNotNone(role)
        self.assertEqual("Artist", role.label)
        self.assertEqual("artist", role.tier)

    def test_role_from_api_falls_back_to_permissions_for_unsupported_visible_role(self):
        role = role_from_api(3, visible_role="set-designer")

        self.assertIsNotNone(role)
        self.assertEqual("Developer", role.label)
        self.assertEqual("developer", role.tier)

    def test_elevated_permission_accepts_any_numeric_value_above_one(self):
        self.assertTrue(is_elevated_permission(2))
        self.assertTrue(is_elevated_permission("6"))
        self.assertTrue(is_elevated_permission(7))
        self.assertFalse(is_elevated_permission(1))
        self.assertFalse(is_elevated_permission("nope"))

    def test_coerce_permissions_returns_none_for_unusable_values(self):
        self.assertEqual(3, coerce_permissions("3"))
        self.assertIsNone(coerce_permissions(None))
        self.assertIsNone(coerce_permissions("bad"))

    def test_debug_forced_permission_uses_selected_role(self):
        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "3"}):
            forced_permission = debug_forced_role_permission()
            role = role_from_permissions(1, forced_permission=forced_permission)

        self.assertEqual(3, forced_permission)
        self.assertEqual("Developer", role.label)
        self.assertEqual("developer", role.tier)

    def test_debug_forced_role_tier_uses_selected_visible_role(self):
        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "event_manager"}):
            forced_permission = debug_forced_role_permission()
            role = role_from_api(1, forced_permission=forced_permission)

        self.assertEqual("Event Manager", role.label)
        self.assertEqual("event_manager", role.tier)
        self.assertFalse(is_elevated_permission(1, forced_permission=forced_permission))

    def test_debug_forced_role_slug_uses_selected_visible_role(self):
        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "code-reviewer"}):
            forced_permission = debug_forced_role_permission()
            role = role_from_api(1, forced_permission=forced_permission)

        self.assertEqual("Code Reviewer", role.label)
        self.assertEqual("code_reviewer", role.tier)

    def test_debug_forced_registered_permission_suppresses_role(self):
        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "1"}):
            forced_permission = debug_forced_role_permission()
            role = role_from_permissions(2, forced_permission=forced_permission)

        self.assertEqual(1, forced_permission)
        self.assertIsNone(role)

    def test_debug_forced_registered_permission_is_not_elevated(self):
        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "1"}):
            self.assertFalse(
                is_elevated_permission(
                    2,
                    forced_permission=debug_forced_role_permission(),
                )
            )

    def test_debug_forced_permission_forces_elevated_permission(self):
        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "5"}):
            self.assertTrue(
                is_elevated_permission(
                    1,
                    forced_permission=debug_forced_role_permission(),
                )
            )

    def test_debug_forced_permission_ignores_unknown_values(self):
        for value in ("", "nope", "99"):
            with self.subTest(value=value):
                with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: value}):
                    self.assertIsNone(debug_forced_role_permission())

    def test_roles_grant_dev_mode_only_for_developer_tiers(self):
        for roles in (
            ["developer"],
            ["developer-junior"],
            ["code-reviewer"],
            ["moderator"],
            ["artist", "developer"],
        ):
            with self.subTest(roles=roles):
                self.assertTrue(roles_grant_dev_mode(roles))

    def test_roles_grant_dev_mode_false_for_non_developer_tiers(self):
        for roles in (
            ["artist"],
            ["writer"],
            ["event-manager"],
            ["play-tester"],
            ["artist", "writer"],
            [],
            None,
        ):
            with self.subTest(roles=roles):
                self.assertFalse(roles_grant_dev_mode(roles))

    def test_resolve_dev_mode_prefers_displayable_roles(self):
        self.assertTrue(resolve_dev_mode(1, ["developer"]))
        self.assertTrue(resolve_dev_mode(1, ["code-reviewer"]))
        self.assertFalse(resolve_dev_mode(6, ["artist"]))

    def test_resolve_dev_mode_falls_back_to_permissions_when_roles_unavailable(self):
        self.assertTrue(resolve_dev_mode(3, None))
        self.assertTrue(resolve_dev_mode(6, None))
        self.assertFalse(resolve_dev_mode(1, None))

    def test_resolve_dev_mode_empty_roles_do_not_fall_back(self):
        self.assertFalse(resolve_dev_mode(6, []))

    def test_resolve_dev_mode_forced_permission_uses_dev_tiers(self):
        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "3"}):
            self.assertTrue(
                resolve_dev_mode(1, None, forced_permission=debug_forced_role_permission())
            )
        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "5"}):
            self.assertFalse(
                resolve_dev_mode(1, None, forced_permission=debug_forced_role_permission())
            )
        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "1"}):
            self.assertFalse(
                resolve_dev_mode(3, None, forced_permission=debug_forced_role_permission())
            )

    def test_resolve_dev_mode_forced_role_uses_dev_tiers(self):
        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "code-reviewer"}):
            self.assertTrue(
                resolve_dev_mode(1, None, forced_permission=debug_forced_role_permission())
            )
        with patch.dict("os.environ", {DEBUG_FORCE_ROLE_PERMISSION_ENV: "artist"}):
            self.assertFalse(
                resolve_dev_mode(1, None, forced_permission=debug_forced_role_permission())
            )

    def test_badge_style_selection_uses_role_tier(self):
        self.assertEqual("#F0B450", role_badge_style("junior_developer")["accent"])
        self.assertEqual("#5FD07F", role_badge_style("developer")["accent"])
        self.assertEqual("#D98FE6", role_badge_style("event_manager")["accent"])
        self.assertEqual("#F28D4F", role_badge_style("artist")["accent"])
        self.assertEqual("#F2D35C", role_badge_style("play_tester")["accent"])
        self.assertEqual("#7DC5FF", role_badge_style("writer")["accent"])
        self.assertEqual("#B0A0F0", role_badge_style("code_reviewer")["accent"])
        self.assertEqual("#6FCFE2", role_badge_style("moderator")["accent"])
        self.assertEqual("#EF6461", role_badge_style("admin")["accent"])
        self.assertEqual("#F0B450", role_badge_style("unknown")["accent"])

    def test_badge_icons_match_expected_tiers(self):
        expected = {
            "junior_developer": "code",
            "developer": "code",
            "code_reviewer": "search",
            "moderator": "shield",
            "event_manager": "star",
            "artist": "palette",
            "play_tester": "controller",
            "writer": "pen",
        }
        for tier, icon in expected.items():
            with self.subTest(tier=tier):
                self.assertEqual(icon, role_badge_style(tier).get("icon"))

        for tier in ("admin", "unknown"):
            with self.subTest(tier=tier):
                self.assertIsNone(role_badge_style(tier).get("icon"))


if __name__ == "__main__":
    unittest.main()
