import unittest

from worker_fakes import WorkerHarness, activity

SECRET_USERNAME = "private_user"
SECRET_API_KEY = "SECRET_API_KEY"
SECRET_RP_TEXT = "secret rich presence text"


class WorkerLoggingTests(unittest.TestCase):
    def _run_one_loop_with_logs(self, fail_update=False):
        run = WorkerHarness(
            [activity(rich_presence=SECRET_RP_TEXT)],
            username=SECRET_USERNAME, apikey=SECRET_API_KEY,
        )
        if fail_update:
            run.gateway.update_error = RuntimeError("discord update broke")
        with self.assertLogs("desktop.runtime.worker", level="INFO") as logs:
            run.run()
        output = "\n".join(logs.output)
        self.assertNotIn(SECRET_USERNAME, output)
        self.assertNotIn(SECRET_API_KEY, output)
        self.assertNotIn(SECRET_RP_TEXT, output)
        self.assertNotIn("retroachievements.org/user", output)
        return output

    def test_presence_update_success_logs_safe_metadata(self):
        output = self._run_one_loop_with_logs()
        self.assertIn("[RA] connection_succeeded", output)
        self.assertIn("[DISCORD] presence_update_attempt game_id=123", output)
        self.assertIn("[DISCORD] presence_update_succeeded game_id=123", output)
        self.assertIn("achievements=4/10", output)

    def test_presence_update_failure_logs_safe_metadata(self):
        output = self._run_one_loop_with_logs(fail_update=True)
        self.assertIn("[DISCORD] presence_update_failed game_id=123", output)
        self.assertIn("error_type=RuntimeError", output)


if __name__ == "__main__":
    unittest.main()
