import unittest

from desktop.core.roles import (
    coerce_permissions,
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
            5: ("Moderator", "moderator"),
            6: ("Moderator", "moderator"),
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

    def test_badge_style_selection_uses_role_tier(self):
        self.assertEqual("#F0B450", role_badge_style("junior_developer")["accent"])
        self.assertEqual("#5FD07F", role_badge_style("developer")["accent"])
        self.assertEqual("#B0A0F0", role_badge_style("code_reviewer")["accent"])
        self.assertEqual("#6FCFE2", role_badge_style("moderator")["accent"])
        self.assertEqual("#F0B450", role_badge_style("unknown")["accent"])


if __name__ == "__main__":
    unittest.main()
