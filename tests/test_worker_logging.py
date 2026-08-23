import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from desktop.runtime.worker import RPCWorker

SECRET_USERNAME = "private_user"
SECRET_API_KEY = "SECRET_API_KEY"
SECRET_RP_TEXT = "secret rich presence text"


class LoopPresence:
    def __init__(self, worker, fail_update=False):
        self.worker = worker
        self.fail_update = fail_update
        self.pipe = None

    def connect(self):
        pass

    def update(self, **kwargs):
        self.worker._stop_event.set()
        if self.fail_update:
            raise RuntimeError("discord update broke")

    def clear(self):
        pass

    def close(self):
        pass


def _summary_payload():
    return {
        "LastGameID": 123,
        "RichPresenceMsg": SECRET_RP_TEXT,
        "RichPresenceMsgDate": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "Awarded": {
            "123": {
                "NumPossibleAchievements": 10,
                "NumAchieved": 4,
                "NumAchievedHardcore": 3,
            }
        },
    }


def _game_payload():
    return {
        "GameTitle": "Private Game Title",
        "ConsoleName": "NES",
        "ConsoleID": "7",
        "ImageIcon": "/Images/000123.png",
    }


class WorkerLoggingTests(unittest.TestCase):
    def _make_worker(self, fail_update=False):
        worker = RPCWorker(
            initial_config={
                "username": SECRET_USERNAME,
                "apikey": SECRET_API_KEY,
                "show_profile_button": True,
                "show_gamepage_button": True,
                "show_achievement_progress": True,
            },
            console_icons={"7": "nes-icon"},
        )

        def presence_factory(client_id, pipe=None):
            presence = LoopPresence(worker, fail_update=fail_update)
            presence.pipe = pipe
            return presence

        worker._presence_factory = presence_factory
        worker.running = True
        return worker

    def _run_one_loop_with_logs(self, worker):
        with (
            patch(
                "desktop.runtime.worker.ra_get_user_summary",
                return_value=_summary_payload(),
            ),
            patch("desktop.runtime.worker.ra_get_game", return_value=_game_payload()),
            self.assertLogs("desktop.runtime.worker", level="INFO") as logs,
        ):
            worker._loop()
        return "\n".join(logs.output)

    def test_presence_update_success_logs_safe_metadata(self):
        output = self._run_one_loop_with_logs(self._make_worker())

        self.assertIn("[RA] connection_succeeded", output)
        self.assertIn("[DISCORD] presence_update_attempt game_id=123", output)
        self.assertIn("[DISCORD] presence_update_succeeded game_id=123", output)
        self.assertIn("achievements=4/10", output)
        self.assertNotIn(SECRET_USERNAME, output)
        self.assertNotIn(SECRET_API_KEY, output)
        self.assertNotIn(SECRET_RP_TEXT, output)
        self.assertNotIn("retroachievements.org/user", output)

    def test_presence_update_failure_logs_safe_metadata(self):
        output = self._run_one_loop_with_logs(self._make_worker(fail_update=True))

        self.assertIn("[DISCORD] presence_update_failed game_id=123", output)
        self.assertIn("error_type=RuntimeError", output)
        self.assertNotIn(SECRET_USERNAME, output)
        self.assertNotIn(SECRET_API_KEY, output)
        self.assertNotIn(SECRET_RP_TEXT, output)
        self.assertNotIn("retroachievements.org/user", output)


if __name__ == "__main__":
    unittest.main()
