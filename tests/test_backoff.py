import unittest

from desktop.runtime.backoff import BackoffPolicy


class BackoffPolicyTests(unittest.TestCase):
    def test_no_errors_uses_poll_interval(self):
        self.assertEqual(5, BackoffPolicy(5).delay_for(0))

    def test_errors_double_until_the_legacy_exponent_cap(self):
        policy = BackoffPolicy(5)

        self.assertEqual(10, policy.delay_for(1))
        self.assertEqual(20, policy.delay_for(2))
        self.assertEqual(40, policy.delay_for(3))
        self.assertEqual(60, policy.delay_for(4))
        self.assertEqual(60, policy.delay_for(5))

    def test_max_delay_caps_large_intervals(self):
        self.assertEqual(60, BackoffPolicy(30).delay_for(1))


if __name__ == "__main__":
    unittest.main()
