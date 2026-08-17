import sys
import types
import unittest
from unittest.mock import Mock, patch

from casper import device_actions


class DeviceActionTests(unittest.TestCase):
    def setUp(self):
        self.apps = [
            {
                "id": "steam-id",
                "name": "Steam",
                "path": "C:/Steam/steam.exe",
                "kind": "executable",
            }
        ]

    def test_rejects_candidate_outside_catalog(self):
        planned = {
            "action": "OPEN_APP",
            "candidate_id": "invented-id",
            "reason": "",
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, self.apps),
        ):
            result = device_actions.execute_user_request(
                "打开 Steam", "", applications=self.apps
            )
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])

    def test_ai_owns_bounded_volume_action(self):
        planned = {
            "action": "VOLUME_UP",
            "candidate_id": None,
            "reason": "user asked for one step",
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, self.apps),
        ), patch.object(
            device_actions,
            "execute_system_control",
            return_value=True,
        ) as control:
            result = device_actions.execute_user_request(
                "音量调高一点", "", applications=self.apps
            )
        control.assert_called_once_with("VOLUME_UP")
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "system_control_completed")

    def test_window_action_requires_discovered_window_id(self):
        window = {
            "id": "window-id",
            "name": "Steam",
            "kind": "window",
            "window_handle": 123,
        }
        planned = {
            "action": "MINIMIZE_WINDOW",
            "candidate_id": "window-id",
            "reason": "selected current window",
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, self.apps + [window]),
        ), patch.object(
            device_actions,
            "select_window_action",
            return_value={
                "action": "MINIMIZE_WINDOW",
                "candidate_id": "window-id",
            },
        ), patch.object(
            device_actions,
            "execute_window_control",
            return_value=True,
        ) as control:
            result = device_actions.execute_user_request(
                "把 Steam 最小化", "", applications=self.apps + [window]
            )
        control.assert_called_once_with("MINIMIZE_WINDOW", window)
        self.assertTrue(result["success"])
        self.assertEqual(result["window"], "Steam")

    def test_window_action_rejects_invented_id(self):
        planned = {
            "action": "FOCUS_WINDOW",
            "candidate_id": "invented-window",
            "reason": "invented",
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, self.apps),
        ), patch.object(
            device_actions,
            "select_window_action",
            return_value=None,
        ), patch.object(
            device_actions,
            "execute_window_control",
        ) as control:
            result = device_actions.execute_user_request(
                "切到 Steam", "", applications=self.apps
            )
        control.assert_not_called()
        self.assertTrue(result["needs_clarification"])

    def test_focused_ai_replaces_wrong_generic_window_selection(self):
        edge = {
            "id": "edge-window",
            "name": "Microsoft Edge",
            "kind": "window",
            "window_handle": 111,
        }
        steam = {
            "id": "steam-window",
            "name": "Steam",
            "kind": "window",
            "window_handle": 222,
        }
        generic_plan = {
            "action": "RESTORE_WINDOW",
            "candidate_id": "edge-window",
            "reason": "incorrect generic selection",
        }
        launched = []
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(generic_plan, self.apps + [edge, steam]),
        ), patch.object(
            device_actions,
            "select_window_action",
            return_value={
                "action": "FOCUS_WINDOW",
                "candidate_id": "steam-window",
            },
        ), patch.object(
            device_actions,
            "execute_window_control",
            return_value=True,
        ) as control:
            result = device_actions.execute_user_request(
                "切换到 Steam 窗口",
                "",
                applications=self.apps + [edge, steam],
                launcher=launched.append,
            )
        control.assert_called_once_with("FOCUS_WINDOW", steam)
        self.assertTrue(result["success"])
        self.assertEqual(result["window"], "Steam")

    def test_open_app_with_window_id_is_retyped_by_focused_ai(self):
        steam = {
            "id": "steam-window",
            "name": "Steam",
            "kind": "window",
            "window_handle": 222,
        }
        malformed = {
            "action": "OPEN_APP",
            "candidate_id": "steam-window",
            "reason": "wrong action type",
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(malformed, self.apps + [steam]),
        ), patch.object(
            device_actions,
            "classify_device_action_family",
            return_value="WINDOW_CONTROL",
        ), patch.object(
            device_actions,
            "select_window_action",
            return_value={
                "action": "FOCUS_WINDOW",
                "candidate_id": "steam-window",
            },
        ), patch.object(
            device_actions,
            "execute_window_control",
            return_value=True,
        ) as control:
            result = device_actions.execute_user_request(
                "切换到 Steam 窗口",
                "",
                applications=self.apps + [steam],
            )
        control.assert_called_once_with("FOCUS_WINDOW", steam)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "window_control_completed")

    def test_window_family_blocks_wrong_valid_application_candidate(self):
        code = {
            "id": "code-id",
            "name": "code",
            "path": "C:/VSCode/Code.exe",
            "kind": "executable",
        }
        steam_window = {
            "id": "steam-window",
            "name": "Steam",
            "kind": "window",
            "window_handle": 222,
        }
        wrong_generic_plan = {
            "action": "OPEN_APP",
            "candidate_id": "code-id",
            "reason": "wrong but structurally valid app selection",
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(wrong_generic_plan, [code, steam_window]),
        ), patch.object(
            device_actions,
            "classify_device_action_family",
            return_value="WINDOW_CONTROL",
        ), patch.object(
            device_actions,
            "select_window_action",
            return_value={
                "action": "FOCUS_WINDOW",
                "candidate_id": "steam-window",
            },
        ), patch.object(
            device_actions,
            "execute_window_control",
            return_value=True,
        ) as control, patch.object(
            device_actions,
            "_launch",
        ) as launch:
            result = device_actions.execute_user_request(
                "切换到 Steam 窗口",
                "",
                applications=[code, steam_window],
            )
        launch.assert_not_called()
        control.assert_called_once_with("FOCUS_WINDOW", steam_window)
        self.assertTrue(result["success"])
        self.assertEqual(result["window"], "Steam")

    def test_opens_only_catalog_candidate(self):
        planned = {
            "action": "OPEN_APP",
            "candidate_id": "steam-id",
            "reason": "requested",
        }
        launched = []
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, self.apps),
        ):
            result = device_actions.execute_user_request(
                "打开 Steam",
                "",
                applications=self.apps,
                launcher=launched.append,
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["application"], "Steam")
        self.assertEqual(launched, [self.apps[0]])

    def test_accepts_bare_catalog_id_without_accepting_commands(self):
        launched = []
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=("steam-id", self.apps),
        ):
            result = device_actions.execute_user_request(
                "打开 Steam",
                "",
                applications=self.apps,
                launcher=launched.append,
            )
        self.assertTrue(result["success"])
        self.assertEqual(launched, [self.apps[0]])

        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=("powershell -Command evil", self.apps),
        ):
            rejected = device_actions.execute_user_request(
                "打开 Steam",
                "",
                applications=self.apps,
                launcher=launched.append,
            )
        self.assertFalse(rejected["success"])
        self.assertEqual(launched, [self.apps[0]])

    def test_recovers_only_valid_id_from_truncated_json(self):
        truncated = (
            '{"action":"OPEN_APP","candidate_id":"steam-id",'
            '"library_type":null,"clarification":'
        )
        launched = []
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(truncated, self.apps),
        ):
            result = device_actions.execute_user_request(
                "打开第二个",
                "",
                applications=self.apps,
                launcher=launched.append,
            )
        self.assertTrue(result["success"])
        self.assertEqual(launched, [self.apps[0]])

        invented = truncated.replace("steam-id", "invented-id")
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(invented, self.apps),
        ):
            rejected = device_actions.execute_user_request(
                "打开第二个",
                "",
                applications=self.apps,
                launcher=launched.append,
            )
        self.assertFalse(rejected["success"])
        self.assertEqual(launched, [self.apps[0]])

    def test_retries_ai_when_candidate_id_itself_is_truncated(self):
        truncated = '{"action":"OPEN_APP","candidate_id":"ste'
        launched = []
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(truncated, self.apps),
        ), patch.object(
            device_actions,
            "retry_open_app_selection",
            return_value="steam-id",
        ) as retry:
            result = device_actions.execute_user_request(
                "打开 Steam",
                "",
                applications=self.apps,
                launcher=launched.append,
            )
        self.assertEqual(retry.call_count, 1)
        self.assertTrue(result["success"])
        self.assertEqual(launched, [self.apps[0]])

    def test_empty_device_plan_gets_compact_ai_retry(self):
        launched = []
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=("", self.apps),
        ), patch.object(
            device_actions,
            "retry_open_app_selection",
            return_value="steam-id",
        ) as retry:
            result = device_actions.execute_user_request(
                "需要，打开刚才那个",
                "刚才讨论的是 Steam",
                applications=self.apps,
                launcher=launched.append,
            )
        self.assertEqual(retry.call_count, 1)
        self.assertTrue(result["success"])
        self.assertEqual(launched, [self.apps[0]])

    def test_empty_window_plan_retries_without_opening_application(self):
        retry_plan = {
            "action": "CLARIFY",
            "candidate_id": None,
            "library_type": None,
            "clarification": (
                "没有发现正在打开的 Steam 窗口。需要我打开 Steam 吗？"
            ),
            "reason": "No matching open window exists.",
        }
        launched = []
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=("", self.apps),
        ), patch.object(
            device_actions,
            "retry_open_app_selection",
            return_value=retry_plan,
        ) as retry:
            result = device_actions.execute_user_request(
                "切换到 Steam 窗口",
                "",
                applications=self.apps,
                launcher=launched.append,
            )
        self.assertEqual(retry.call_count, 1)
        self.assertTrue(result["needs_clarification"])
        self.assertIn("Steam 窗口", result["clarification"])
        self.assertEqual(launched, [])

    def test_schema_echo_action_gets_compact_ai_retry(self):
        malformed = {
            "action": "OPEN_APP | STEAM",
            "candidate_id": "steam-id",
            "reason": "brief reason",
        }
        corrected = {
            "action": "OPEN_APP",
            "candidate_id": "steam-id",
            "reason": "User requested Steam.",
        }
        launched = []
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(malformed, self.apps),
        ), patch.object(
            device_actions,
            "retry_open_app_selection",
            return_value=corrected,
        ) as retry:
            result = device_actions.execute_user_request(
                "打开 Steam",
                "",
                applications=self.apps,
                launcher=launched.append,
            )
        self.assertEqual(retry.call_count, 1)
        self.assertTrue(result["success"])
        self.assertEqual(launched, [self.apps[0]])

    def test_unsupported_action_never_launches(self):
        planned = {
            "action": "UNSUPPORTED",
            "candidate_id": None,
            "reason": "game launch is phase two",
        }
        launched = []
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, []),
        ):
            result = device_actions.execute_user_request(
                "打开 Steam 里的游戏",
                "",
                applications=[],
                launcher=launched.append,
            )
        self.assertTrue(result["unsupported"])
        self.assertEqual(launched, [])

    def test_opens_discovered_steam_game(self):
        game = {
            "id": "fm26-id",
            "name": "Football Manager 26",
            "kind": "steam_game",
            "app_id": "1904540",
        }
        planned = {
            "action": "OPEN_APP",
            "candidate_id": "fm26-id",
            "reason": "installed Steam game selected",
        }
        launched = []
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, [game]),
        ):
            result = device_actions.execute_user_request(
                "打开 Football Manager 26",
                "",
                applications=[game],
                launcher=launched.append,
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["application"], "Football Manager 26")
        self.assertEqual(launched, [game])

    def test_lists_only_discovered_steam_games(self):
        game = {
            "id": "fm26-id",
            "name": "Football Manager 26",
            "kind": "steam_game",
            "app_id": "1904540",
        }
        planned = {
            "action": "LIST_LIBRARY",
            "candidate_id": None,
            "library_type": "STEAM_GAMES",
            "reason": "user asked for installed games",
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, self.apps + [game]),
        ):
            result = device_actions.execute_user_request(
                "我的 Steam 库里有什么游戏？",
                "",
                applications=self.apps + [game],
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["name"], "Football Manager 26")

    def test_cloud_music_library_is_not_substituted(self):
        planned = {
            "action": "UNSUPPORTED",
            "candidate_id": None,
            "library_type": None,
            "reason": "Spotify account is not connected",
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, self.apps),
        ):
            result = device_actions.execute_user_request(
                "我的 Spotify 收藏里有什么歌？",
                "",
                applications=self.apps,
            )
        self.assertTrue(result["unsupported"])

    def test_launcher_only_result_never_claims_game_opened(self):
        launcher = {
            "id": "genshin-launcher",
            "name": "Genshin Impact",
            "path": "C:/HoYoPlay/launcher.exe",
            "kind": "shortcut",
            "launcher_only": True,
            "launcher_name": "HoYoPlay",
        }
        planned = {
            "action": "OPEN_APP",
            "candidate_id": "genshin-launcher",
            "reason": "selected",
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, [launcher]),
        ):
            result = device_actions.execute_user_request(
                "打开原神",
                "",
                applications=[launcher],
                launcher=lambda item: None,
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "launcher_opened")
        self.assertEqual(result["launcher"], "HoYoPlay")

    def test_discovered_launcher_game_reports_game_opened(self):
        game = {
            "id": "genshin-game",
            "name": "Genshin Impact",
            "path": "D:/HoYoPlay/games/Genshin Impact game/GenshinImpact.exe",
            "kind": "launcher_game",
            "launcher_name": "HoYoPlay",
        }
        planned = {
            "action": "OPEN_APP",
            "candidate_id": "genshin-game",
            "reason": "selected",
        }
        launched = []
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, [game]),
        ):
            result = device_actions.execute_user_request(
                "打开原神",
                "",
                applications=[game],
                launcher=launched.append,
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "opened")
        self.assertEqual(launched, [game])

    def test_ai_selects_registered_shortcut_strategy_without_hardcoded_launcher(self):
        candidate = {
            "id": "old-id",
            "name": "Example Game",
            "path": "C:/Users/Main/Desktop/Example Game.lnk",
            "kind": "shortcut",
        }
        shortcut = {
            "target": "C:/Program Files/Example Launcher/launcher.exe",
            "arguments": "--game=example_global",
            "working": "C:/Program Files/Example Launcher",
        }
        expected = {
            "id": device_actions._candidate_id(
                "expected_executable",
                "C:/Program Files/Example Launcher/games/ExampleGame.exe",
            ),
            "name": "ExampleGame.exe",
            "path": "C:/Program Files/Example Launcher/games/ExampleGame.exe",
        }
        strategy_id = device_actions._candidate_id(
            "launch_strategy",
            shortcut["target"] + "\0" + shortcut["arguments"],
        )
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=lambda *args, **kwargs: {
                "strategy_id": strategy_id,
                "expected_executable_id": expected["id"],
                "launcher_window_id": None,
                "reason": "registered shortcut metadata matches",
            }
        )
        with patch.object(
            device_actions,
            "_resolve_windows_shortcut",
            return_value=shortcut,
        ), patch.object(
            device_actions,
            "_nearby_executables",
            return_value=[expected],
        ), patch.object(
            device_actions,
            "_visible_window_titles",
            return_value=[],
        ), patch.object(
            device_actions.os.path,
            "isfile",
            return_value=True,
        ), patch.object(
            device_actions.os.path,
            "isdir",
            return_value=True,
        ), patch.dict(sys.modules, {"tools": fake_tools}):
            candidate = device_actions.adapt_launch_candidate(candidate)
        self.assertEqual(candidate["path"], shortcut["target"])
        self.assertEqual(candidate["launcher_arguments"], ["--game=example_global"])
        self.assertEqual(candidate["expected_game_executable"], "ExampleGame.exe")

    def test_ai_cannot_invent_launch_strategy(self):
        candidate = {
            "id": "example-id",
            "name": "Example Game",
            "path": "C:/Desktop/Example Game.lnk",
            "kind": "shortcut",
        }
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=lambda *args, **kwargs: {
                "strategy_id": "invented-strategy",
                "expected_executable_id": None,
                "launcher_window_id": None,
                "reason": "invented",
            }
        )
        with patch.object(
            device_actions,
            "_resolve_windows_shortcut",
            return_value={
                "target": "C:/Launcher/launcher.exe",
                "arguments": "--example",
                "working": "C:/Launcher",
            },
        ), patch.object(
            device_actions.os.path,
            "isfile",
            return_value=True,
        ), patch.object(
            device_actions,
            "_nearby_executables",
            return_value=[],
        ), patch.object(
            device_actions,
            "_visible_window_titles",
            return_value=[],
        ), patch.dict(sys.modules, {"tools": fake_tools}):
            result = device_actions.adapt_launch_candidate(candidate)
        self.assertEqual(result, candidate)

    def test_ai_verification_owns_launcher_vs_game_result(self):
        game = {
            "id": "genshin-game",
            "name": "Genshin Impact",
            "path": "D:/HoYoPlay/games/Genshin Impact game/GenshinImpact.exe",
            "kind": "launcher_game",
            "launcher_name": "HoYoPlay",
        }
        planned = {
            "action": "OPEN_APP",
            "candidate_id": "genshin-game",
            "reason": "selected",
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, [game]),
        ), patch.object(
            device_actions,
            "_runtime_snapshot",
            return_value={"processes": [], "windows": []},
        ), patch.object(
            device_actions,
            "_launch",
            return_value=4321,
        ), patch.object(
            device_actions,
            "verify_launch",
            return_value={
                "status": "LAUNCHER_OPENED",
                "reason": "Only HoYoPlay was observed.",
                "evidence": {},
            },
        ):
            result = device_actions.execute_user_request(
                "打开原神",
                "",
                applications=[game],
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "launcher_opened")
        self.assertEqual(result["verification"]["status"], "LAUNCHER_OPENED")

    def test_launcher_control_is_ai_selected_invoked_and_reverified(self):
        game = {
            "id": "genshin-game",
            "name": "Genshin Impact",
            "path": "C:/Program Files/HoYoPlay/launcher.exe",
            "kind": "launcher_game",
            "launcher_name": "HoYoPlay",
            "launcher_arguments": ["--game=hk4e_global"],
            "expected_game_executable": "GenshinImpact.exe",
        }
        planned = {"action": "OPEN_APP", "candidate_id": "genshin-game"}
        control = {
            "id": "play-control",
            "ordinal": 7,
            "name": "Start Game",
            "automation_id": "play",
            "class_name": "Button",
            "control_type": "ControlType.Button",
        }
        with patch.object(
            device_actions, "plan_user_request", return_value=(planned, [game])
        ), patch.object(
            device_actions,
            "_runtime_snapshot",
            return_value={"processes": [], "windows": ["HoYoPlay"]},
        ), patch.object(
            device_actions, "_launch", return_value=1234
        ), patch.object(
            device_actions,
            "verify_launch",
            side_effect=[
                {"status": "LAUNCHER_OPENED", "reason": "launcher", "evidence": {}},
                {"status": "GAME_OPENED", "reason": "game", "evidence": {}},
            ],
        ) as verify, patch.object(
            device_actions, "discover_launcher_controls", return_value=[control]
        ), patch.object(
            device_actions, "choose_launcher_control", return_value=control
        ), patch.object(
            device_actions, "invoke_launcher_control", return_value=True
        ):
            result = device_actions.execute_user_request("打开原神", "")
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(result["action"], "game_opened")
        self.assertEqual(result["launcher_interaction"]["selected_control"], "Start Game")
        self.assertTrue(result["launcher_interaction"]["invoked"])

    def test_invalid_launch_verifier_json_gets_compact_ai_retry(self):
        game = {
            "name": "Genshin Impact",
            "path": "C:/Program Files/HoYoPlay/launcher.exe",
            "kind": "launcher_game",
            "launcher_name": "HoYoPlay",
            "expected_game_executable": "GenshinImpact.exe",
        }
        snapshot = {"processes": [], "windows": ["HoYoPlay"]}
        model = Mock(side_effect=["", "LAUNCHER_OPENED"])
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}), patch.object(
            device_actions.time, "sleep", return_value=None
        ), patch.object(
            device_actions, "_runtime_snapshot", return_value=snapshot
        ):
            result = device_actions.verify_launch(game, snapshot, 1234)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(result["status"], "LAUNCHER_OPENED")

    def test_recovers_complete_status_from_truncated_verifier_json(self):
        game = {
            "name": "Genshin Impact",
            "path": "C:/Program Files/HoYoPlay/launcher.exe",
            "kind": "launcher_game",
            "launcher_name": "HoYoPlay",
            "expected_game_executable": "GenshinImpact.exe",
        }
        snapshot = {"processes": [], "windows": ["HoYoPlay"]}
        model = Mock(return_value='{"status":"LAUNCHER_OPENED",')
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}), patch.object(
            device_actions.time, "sleep", return_value=None
        ), patch.object(
            device_actions, "_runtime_snapshot", return_value=snapshot
        ):
            result = device_actions.verify_launch(game, snapshot, 1234)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["status"], "LAUNCHER_OPENED")

    def test_unsupported_game_opened_is_ai_reclassified(self):
        game = {
            "name": "Genshin Impact",
            "path": "C:/Program Files/HoYoPlay/launcher.exe",
            "kind": "launcher_game",
            "launcher_name": "HoYoPlay",
            "expected_game_executable": "GenshinImpact.exe",
        }
        snapshot = {"processes": [], "windows": ["HoYoPlay"]}
        model = Mock(side_effect=["", "GAME_OPENED", "LAUNCHER_OPENED"])
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}), patch.object(
            device_actions.time, "sleep", return_value=None
        ), patch.object(
            device_actions, "_runtime_snapshot", return_value=snapshot
        ):
            result = device_actions.verify_launch(game, snapshot, 1234)
        self.assertEqual(result["status"], "LAUNCHER_OPENED")
        self.assertIn("reclassified", result["reason"])

    def test_extended_verification_stops_when_game_process_appears(self):
        game = {
            "name": "Genshin Impact",
            "path": "C:/Program Files/HoYoPlay/launcher.exe",
            "kind": "launcher_game",
            "launcher_name": "HoYoPlay",
            "expected_game_executable": "GenshinImpact.exe",
        }
        before = {"processes": [], "windows": ["HoYoPlay"]}
        snapshots = [
            {"processes": [], "windows": ["HoYoPlay"]},
            {
                "processes": [{"name": "GenshinImpact.exe", "pid": 88}],
                "windows": ["HoYoPlay", "Genshin Impact"],
            },
        ]
        model = Mock(
            return_value='{"status":"GAME_OPENED","reason":"target observed"}'
        )
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}), patch.object(
            device_actions.time, "sleep", return_value=None
        ) as sleeper, patch.object(
            device_actions, "_runtime_snapshot", side_effect=snapshots
        ):
            result = device_actions.verify_launch(
                game, before, None, wait_seconds=35
            )
        self.assertEqual(sleeper.call_count, 2)
        self.assertEqual(result["status"], "GAME_OPENED")

    def test_visual_fallback_clicks_only_after_ai_target_and_reverifies(self):
        game = {
            "id": "genshin-game",
            "name": "Genshin Impact",
            "path": "C:/Program Files/HoYoPlay/launcher.exe",
            "kind": "launcher_game",
            "launcher_name": "HoYoPlay",
        }
        planned = {"action": "OPEN_APP", "candidate_id": "genshin-game"}
        target = {
            "action": "CLICK",
            "x": 820,
            "y": 850,
            "label": "Start Game",
            "confidence": 0.94,
        }
        fake_vision = types.SimpleNamespace(
            locate_launcher_start_control=Mock(return_value=target)
        )
        with patch.dict(sys.modules, {"vision": fake_vision}), patch.object(
            device_actions, "plan_user_request", return_value=(planned, [game])
        ), patch.object(
            device_actions,
            "_runtime_snapshot",
            return_value={"processes": [], "windows": ["HoYoPlay"]},
        ), patch.object(
            device_actions, "_launch", return_value=1234
        ), patch.object(
            device_actions,
            "verify_launch",
            side_effect=[
                {"status": "LAUNCHER_OPENED", "reason": "launcher", "evidence": {}},
                {"status": "GAME_OPENED", "reason": "game", "evidence": {}},
            ],
        ) as verify, patch.object(
            device_actions, "discover_launcher_controls", return_value=[]
        ), patch.object(
            device_actions,
            "capture_launcher_window",
            return_value={
                "window_handle": 9,
                "bounds": (100, 100, 900, 700),
                "file_path": "launcher.jpg",
                "size": (800, 600),
            },
        ), patch.object(
            device_actions, "click_visual_launcher_target", return_value=True
        ) as click:
            result = device_actions.execute_user_request("打开原神", "")
        self.assertEqual(verify.call_count, 2)
        click.assert_called_once()
        self.assertEqual(result["action"], "game_opened")
        self.assertEqual(result["launcher_interaction"]["method"], "vision")
        self.assertEqual(result["launcher_interaction"]["visual_label"], "Start Game")

    def test_send_input_fallback_uses_virtual_desktop_coordinates(self):
        class FakeUser32:
            def GetSystemMetrics(self, index):
                return {76: -1920, 77: 0, 78: 3840, 79: 1080}[index]

            def SendInput(self, count, inputs, size):
                self.count = count
                self.size = size
                return count

        user32 = FakeUser32()
        self.assertTrue(device_actions._send_absolute_click(user32, 1223, 733))
        self.assertEqual(user32.count, 3)

    def test_elevated_launcher_keeps_native_game_arguments(self):
        class FakeShell32:
            def ShellExecuteW(self, *arguments):
                self.arguments = arguments
                return 42

        shell32 = FakeShell32()
        result = device_actions._shell_execute_runas(
            shell32,
            "C:/Program Files/HoYoPlay/launcher.exe",
            ["--game=hk4e_global"],
            "C:/Program Files/HoYoPlay",
        )
        self.assertEqual(result, 42)
        self.assertIsNone(shell32.arguments[0])
        self.assertEqual(shell32.arguments[1], "runas")
        self.assertEqual(shell32.arguments[2], "C:/Program Files/HoYoPlay/launcher.exe")
        self.assertEqual(shell32.arguments[3], "--game=hk4e_global")

    def test_elevation_requires_chat_approval_before_uac(self):
        game = {
            "id": "genshin-game",
            "name": "Genshin Impact",
            "path": "D:/HoYoPlay/games/Genshin Impact game/GenshinImpact.exe",
            "kind": "launcher_game",
            "launcher_name": "HoYoPlay",
        }
        planned = {
            "action": "OPEN_APP",
            "candidate_id": "genshin-game",
            "reason": "selected",
        }
        elevation_error = OSError("elevation required")
        elevation_error.winerror = 740
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, [game]),
        ), patch.object(
            device_actions,
            "_runtime_snapshot",
            return_value={"processes": [], "windows": []},
        ), patch.object(
            device_actions,
            "_launch",
            side_effect=elevation_error,
        ):
            result = device_actions.execute_user_request(
                "打开原神",
                "",
                applications=[game],
            )
        self.assertFalse(result["success"])
        self.assertTrue(result["requires_approval"])
        self.assertEqual(result["approval_type"], "permission_escalation")

    def test_file_action_family_dispatches_to_bounded_file_executor(self):
        planned = {
            "action": "UNSUPPORTED",
            "candidate_id": None,
            "reason": "generic planner deferred",
        }
        expected = {
            "success": True,
            "completed": True,
            "action": "listed_folder",
            "folder": "Downloads",
            "items": [],
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, []),
        ), patch.object(
            device_actions,
            "classify_device_action_family",
            return_value="FILE_ACTION",
        ), patch(
            "casper.file_actions.execute",
            return_value=expected,
        ) as execute:
            result = device_actions.execute_user_request(
                "下载文件夹里有什么？", ""
            )
        execute.assert_called_once_with("下载文件夹里有什么？", "")
        self.assertEqual(result, expected)

    def test_invalid_file_library_scope_blocks_wrong_library_execution(self):
        planned = {
            "action": "LIST_LIBRARY",
            "candidate_id": None,
            "library_type": "LOCAL_MUSIC",
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, []),
        ), patch.object(
            device_actions,
            "classify_file_or_library_scope",
            return_value="",
        ):
            result = device_actions.execute_user_request(
                "下载文件夹里有什么？", ""
            )
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])
        self.assertNotEqual(result.get("action"), "listed_library")

    def test_recycle_scope_dispatches_to_read_only_executor(self):
        planned = {
            "action": "LIST_LIBRARY",
            "candidate_id": None,
            "library_type": "LOCAL_MUSIC",
        }
        expected = {
            "success": True,
            "completed": True,
            "action": "listed_recycle_bin",
            "items": [],
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, []),
        ), patch.object(
            device_actions,
            "classify_file_or_library_scope",
            return_value="RECYCLE_BIN_ACTION",
        ), patch(
            "casper.recycle_bin.execute",
            return_value=expected,
        ) as execute:
            result = device_actions.execute_user_request(
                "回收站里有什么？", ""
            )
        execute.assert_called_once_with(
            "回收站里有什么？", "", approval=None
        )
        self.assertEqual(result, expected)

    def test_window_id_for_recycle_request_bypasses_window_control(self):
        planned = {
            "action": "OPEN_APP",
            "candidate_id": "bekki-window",
        }
        windows = [
            {"id": "bekki-window", "name": "Bekki AI", "kind": "window"}
        ]
        expected = {
            "success": True,
            "completed": True,
            "action": "opened_recycle_bin",
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, windows),
        ), patch.object(
            device_actions,
            "classify_recycle_bin_scope",
            return_value="RECYCLE_BIN_ACTION",
        ), patch(
            "casper.recycle_bin.execute",
            return_value=expected,
        ) as execute, patch.object(
            device_actions, "select_window_action"
        ) as select_window:
            result = device_actions.execute_user_request(
                "打开回收站", ""
            )
        execute.assert_called_once_with("打开回收站", "", approval=None)
        select_window.assert_not_called()
        self.assertEqual(result, expected)

    def test_confirmed_recycle_restore_bypasses_generic_planner(self):
        approval = {
            "action": "restore_recycle_item",
            "candidate_id": "approved-item-id",
        }
        expected = {
            "success": True,
            "completed": True,
            "action": "restored_recycle_item",
            "name": "version_info",
        }
        with patch.object(
            device_actions, "plan_user_request"
        ) as generic_plan, patch(
            "casper.recycle_bin.execute",
            return_value=expected,
        ) as execute:
            result = device_actions.execute_user_request(
                "恢复回收站里的 version_info",
                "",
                device_approval=approval,
            )
        generic_plan.assert_not_called()
        execute.assert_called_once_with(
            "恢复回收站里的 version_info",
            "",
            approval=approval,
        )
        self.assertEqual(result, expected)

    def test_restore_window_misplan_for_recycle_file_enters_recycle_flow(self):
        planned = {
            "action": "RESTORE_WINDOW",
            "candidate_id": "vscode-window",
        }
        windows = [
            {
                "id": "vscode-window",
                "name": "Visual Studio Code",
                "kind": "window",
            }
        ]
        expected = {
            "success": False,
            "requires_approval": True,
            "action": "restore_recycle_item",
            "candidate_id": "recycle-item-id",
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, windows),
        ), patch.object(
            device_actions,
            "classify_recycle_bin_scope",
            return_value="RECYCLE_BIN_ACTION",
        ), patch(
            "casper.recycle_bin.execute",
            return_value=expected,
        ) as execute, patch.object(
            device_actions, "select_window_action"
        ) as select_window:
            result = device_actions.execute_user_request(
                "恢复回收站里的 version_info", ""
            )
        execute.assert_called_once_with(
            "恢复回收站里的 version_info", "", approval=None
        )
        select_window.assert_not_called()
        self.assertEqual(result, expected)

    def test_recycle_pre_router_survives_truncated_generic_planner(self):
        expected = {
            "success": True,
            "completed": True,
            "action": "listed_recycle_bin",
            "items": [],
        }
        with patch.object(
            device_actions,
            "classify_recycle_bin_scope",
            return_value="RECYCLE_BIN_ACTION",
        ), patch.object(
            device_actions, "plan_user_request"
        ) as generic_plan, patch(
            "casper.recycle_bin.execute",
            return_value=expected,
        ) as execute:
            result = device_actions.execute_user_request(
                "回收站里有什么？", ""
            )
        generic_plan.assert_not_called()
        execute.assert_called_once_with(
            "回收站里有什么？", "", approval=None
        )
        self.assertEqual(result, expected)

    def test_file_family_overrides_wrong_local_music_library_plan(self):
        planned = {
            "action": "LIST_LIBRARY",
            "candidate_id": None,
            "library_type": "LOCAL_MUSIC",
            "reason": "incorrect generic planner scope",
        }
        expected = {
            "success": True,
            "completed": True,
            "action": "listed_folder",
            "folder": "Downloads",
            "items": [{"name": "setup.exe", "kind": "file"}],
        }
        with patch.object(
            device_actions,
            "plan_user_request",
            return_value=(planned, []),
        ), patch.object(
            device_actions,
            "classify_file_or_library_scope",
            return_value="FILE_ACTION",
        ), patch(
            "casper.file_actions.execute",
            return_value=expected,
        ) as execute:
            result = device_actions.execute_user_request(
                "下载文件夹里有什么？", ""
            )
        execute.assert_called_once_with("下载文件夹里有什么？", "")
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
