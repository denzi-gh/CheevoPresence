from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
from typing import ClassVar
from unittest.mock import Mock, patch

from desktop.core.ra_models import PlayerGameActivity, UserActivity
from desktop.runtime.worker import RPCWorker

NOW = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)


def activity(**overrides):
    return UserActivity(**({
        "game_id": 123,
        "game_title": "Mega Game",
        "rich_presence": "Playing Level 1",
        "rich_presence_updated_at": NOW,
        "visible_role": "artist",
        "displayable_roles": ("artist",),
    } | overrides))


def game_info(**overrides):
    return {
        "Title": "Mega Game", "ConsoleName": "NES", "ConsoleID": "7",
        "ImageIcon": "/Images/000123.png", "NumAchievements": 10,
        "NumAwardedToUser": 4, "NumAwardedToUserHardcore": 3, "UserTotalPlaytime": 900,
    } | overrides


def progress(game_id=123, achieved=4, hardcore=3, total=10):
    return {str(game_id): {
        "NumPossibleAchievements": total, "NumAchieved": achieved, "NumAchievedHardcore": hardcore,
    }}


def player_game(game_id=123, soft=None, hard=None):
    return PlayerGameActivity(game_id, soft, hard)


class RecordingGateway:
    def __init__(self):
        self.rpc = None
        self.rpc_connected = False
        self.rpc_pipe = None
        self.start_time = None
        self.updates = []
        self.update_error = None
        self.connect_available = True

    def connect(self):
        if not self.connect_available:
            return False
        if not self.rpc_connected:
            self.rpc_connected = True
            self.rpc_pipe = 0
            self.start_time = int(NOW.timestamp())
        return True

    def update(self, **kwargs):
        if self.update_error:
            error, self.update_error = self.update_error, None
            raise error
        self.updates.append(deepcopy(kwargs))

    def disconnect(self):
        self.rpc_connected = False
        self.start_time = None


class SynchronousThread:
    def __init__(self, target, **_kwargs):
        self.target = target

    def start(self):
        self.target()

    def is_alive(self):
        return False


class WorkerHarness:
    ENDPOINTS: ClassVar = {
        "activity": "ra_get_user_activity", "info": "ra_get_game_info_and_user_progress",
        "game": "ra_get_game", "progress": "ra_get_user_progress",
        "mode": "ra_get_player_games_v2", "profile": "ra_get_user_profile",
    }

    def __init__(self, activities, **config):
        self.activities = activities
        self.current_activity = activity()
        self.now = NOW
        self.gateway = RecordingGateway()
        self.worker = RPCWorker(
            initial_config={"username": "user", "apikey": "key"} | config,
            console_icons={"7": "nes-icon"}, discord_gateway=self.gateway,
        )
        self.requests = []
        self.snapshots = []
        self.waits = []
        self.api = {
            "activity": Mock(side_effect=self._next_activity),
            "info": Mock(return_value=game_info()),
            "game": Mock(return_value={
                "GameTitle": "Mega Game", "ConsoleName": "NES",
                "ConsoleID": "7", "ImageIcon": "/Images/000123.png",
            }),
            "progress": Mock(side_effect=lambda _u, _k, game_id: progress(game_id)),
            "mode": Mock(side_effect=lambda _u, _k, game_id=None, **_kw: (
                player_game(game_id or self.current_activity.game_id),
            )),
            "profile": Mock(return_value={"Permissions": 1}),
        }

    def _next_activity(self, *_args):
        value = next(self._activity_iter)
        if isinstance(value, Exception):
            raise value
        self.current_activity = value
        return value

    def run(self, *, iterations=None, after_iteration=None, config=None, **seed):
        iterations = len(self.activities) if iterations is None else iterations
        self._activity_iter = iter(self.activities)
        self.current_activity = seed.get("initial_activity") or activity()
        pending = []
        completed = 0

        def sleep(seconds):
            nonlocal completed
            self.requests.append(list(pending))
            pending.clear()
            self.waits.append(seconds)
            self.snapshots.append(self.worker.get_state())
            completed += 1
            if after_iteration:
                after_iteration(completed, self)
            if completed >= iterations:
                self.worker._stop_event.set()

        def record(name):
            def request(*args, **kwargs):
                pending.append(name)
                return self.api[name](*args, **kwargs)
            return request

        self.worker._sleep = sleep
        with ExitStack() as stack:
            unexpected_http = stack.enter_context(patch(
                "requests.Session.request", side_effect=AssertionError("Unexpected HTTP request"),
            ))
            stack.callback(unexpected_http.assert_not_called)
            for name, endpoint in self.ENDPOINTS.items():
                stack.enter_context(patch(f"desktop.runtime.worker.{endpoint}", side_effect=record(name)))
            clock = stack.enter_context(patch("desktop.runtime.worker.datetime"))
            clock.now.side_effect = lambda _tz: self.now
            stack.enter_context(patch("desktop.runtime.worker.time.time", side_effect=lambda: self.now.timestamp()))
            stack.enter_context(patch("desktop.runtime.worker.threading.Thread", SynchronousThread))
            self.worker.start(config or self.worker.config, **seed)
        return self
