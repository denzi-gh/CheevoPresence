import unittest
from unittest.mock import patch

from desktop.core.roles import (
    DEBUG_FORCE_ROLE_PERMISSION_ENV,
    coerce_permissions,
    debug_forced_role_permission,
    is_elevated_permission,
    role_from_permissions,
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

    def test_badge_style_selection_uses_role_tier(self):
        self.assertEqual("#F0B450", role_badge_style("junior_developer")["accent"])
        self.assertEqual("#5FD07F", role_badge_style("developer")["accent"])
        self.assertEqual("#B0A0F0", role_badge_style("code_reviewer")["accent"])
        self.assertEqual("#6FCFE2", role_badge_style("moderator")["accent"])
        self.assertEqual("#EF6461", role_badge_style("admin")["accent"])
        self.assertEqual("#F0B450", role_badge_style("unknown")["accent"])


if __name__ == "__main__":
    unittest.main()
