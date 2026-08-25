import unittest
import sys
import types
from unittest.mock import Mock, patch

from casper import adapters, browser


class AdapterRenderingTests(unittest.TestCase):
    def test_simple_application_target_is_bounded_to_app_launch_commands(self):
        self.assertEqual(adapters._simple_application_target("打开 Steam"), "Steam")
        self.assertEqual(adapters._simple_application_target("打开 Steam 客户端"), "Steam")
        self.assertEqual(adapters._simple_application_target("launch Spotify"), "Spotify")
        self.assertEqual(adapters._simple_application_target("打开回收站"), "")
        self.assertEqual(adapters._simple_application_target("打开下载文件夹"), "")
        self.assertEqual(adapters._simple_application_target("打开原神"), "原神")

    def test_start_menu_launcher_requires_one_exact_app_identity(self):
        listing = types.SimpleNamespace(
            returncode=0,
            stdout='[{"Name":"Steam","AppID":"steam.app"},{"Name":"Microsoft Edge","AppID":"edge.app"}]',
        )
        launched = types.SimpleNamespace(returncode=0, stdout="")
        with patch.object(adapters.os, "name", "nt"), patch(
            "casper.application_skills.get_application",
            return_value=None,
        ), patch(
            "casper.application_skills.remember_application",
            return_value=True,
        ) as remember, patch.object(
            adapters.subprocess,
            "run",
            side_effect=[listing, launched],
        ) as runner, patch.object(
            adapters,
            "_find_exact_start_menu_shortcut",
            return_value=r"C:\Start Menu\Steam.lnk",
        ):
            result = adapters._launch_start_menu_application("Steam")
        self.assertEqual(result["action"], "application_opened")
        self.assertEqual(result["application"], "Steam")
        self.assertEqual(result["launch_route"], "apps_folder")
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(runner.call_args.args[0][0], "explorer.exe")
        self.assertEqual(
            runner.call_args.args[0][1], "shell:AppsFolder\\steam.app"
        )
        remember.assert_called_once()
        self.assertEqual(result["skill_state"], "learned")

    def test_start_menu_launcher_never_substitutes_a_different_window(self):
        listing = types.SimpleNamespace(
            returncode=0,
            stdout='[{"Name":"Microsoft Edge","AppID":"edge.app"}]',
        )
        with patch.object(adapters.os, "name", "nt"), patch(
            "casper.application_skills.get_application",
            return_value=None,
        ), patch(
            "casper.application_skills.select_installed_candidate",
            return_value=None,
        ), patch.object(
            adapters.subprocess,
            "run",
            return_value=listing,
        ), patch.object(
            adapters,
            "_find_exact_start_menu_shortcut",
            return_value="",
        ) as runner:
            result = adapters._launch_start_menu_application("Steam")
        self.assertIsNone(result)
        self.assertEqual(runner.call_count, 1)

    def test_start_menu_launcher_falls_back_to_exact_shortcut(self):
        listing = types.SimpleNamespace(
            returncode=0,
            stdout='[{"Name":"Steam","AppID":"steam.app"}]',
        )
        failed_app_id = types.SimpleNamespace(returncode=2, stdout="")
        shortcut = (
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs"
            r"\Steam\Steam.lnk"
        )
        with patch.object(adapters.os, "name", "nt"), patch(
            "casper.application_skills.get_application",
            return_value=None,
        ), patch(
            "casper.application_skills.remember_application",
            return_value=True,
        ) as remember, patch.object(
            adapters.subprocess,
            "run",
            side_effect=[listing, failed_app_id],
        ), patch.object(
            adapters,
            "_find_exact_start_menu_shortcut",
            return_value=shortcut,
        ) as finder, patch.object(
            adapters,
            "_launch_exact_start_menu_shortcut",
            return_value=True,
        ) as launcher:
            result = adapters._launch_start_menu_application("Steam")
        finder.assert_called_once_with("Steam")
        launcher.assert_called_once_with(shortcut)
        self.assertEqual(result["action"], "application_opened")
        self.assertEqual(result["launch_route"], "start_menu_shortcut")
        self.assertEqual(result["skill_state"], "learned")
        remember.assert_called_once()

    def test_ai_resolves_app_alias_only_from_installed_candidates(self):
        listing = types.SimpleNamespace(
            returncode=0,
            stdout=(
                '[{"Name":"Visual Studio Code","AppID":"vscode.app"},'
                '{"Name":"Microsoft Edge","AppID":"edge.app"}]'
            ),
        )
        launched = types.SimpleNamespace(returncode=1, stdout="")
        selected = {"name": "Visual Studio Code", "app_id": "vscode.app"}
        with patch.object(adapters.os, "name", "nt"), patch(
            "casper.application_skills.get_application",
            return_value=None,
        ), patch(
            "casper.application_skills.select_installed_candidate",
            return_value=selected,
        ) as selector, patch(
            "casper.application_skills.remember_application",
            return_value=True,
        ) as remember, patch.object(
            adapters.subprocess,
            "run",
            side_effect=[listing, launched],
        ), patch.object(
            adapters,
            "_find_exact_start_menu_shortcut",
            return_value=r"C:\Start Menu\Visual Studio Code.lnk",
        ):
            result = adapters._launch_start_menu_application("VS Code")
        selector.assert_called_once()
        remember.assert_called_once()
        self.assertEqual(result["application"], "Visual Studio Code")
        self.assertEqual(result["match_route"], "ai_candidate")
        self.assertEqual(result["skill_state"], "learned")

    def test_ai_resolves_genshin_but_not_generic_hoyoplay_launcher(self):
        listing = types.SimpleNamespace(
            returncode=0,
            stdout=(
                '[{"Name":"Genshin Impact","AppID":"genshin.app"},'
                '{"Name":"HoYoPlay","AppID":"hoyoplay.app"}]'
            ),
        )
        launched = types.SimpleNamespace(returncode=0, stdout="")
        selected = {"name": "Genshin Impact", "app_id": "genshin.app"}
        with patch.object(adapters.os, "name", "nt"), patch(
            "casper.application_skills.get_application",
            return_value=None,
        ), patch(
            "casper.application_skills.select_installed_candidate",
            return_value=selected,
        ) as selector, patch(
            "casper.application_skills.remember_application",
            return_value=True,
        ) as remember, patch.object(
            adapters.subprocess,
            "run",
            side_effect=[listing, launched],
        ), patch.object(
            adapters,
            "_find_exact_start_menu_shortcut",
            return_value=r"C:\Start Menu\Genshin Impact.lnk",
        ):
            result = adapters._launch_start_menu_application("原神")
        selector.assert_called_once()
        remember.assert_called_once()
        self.assertEqual(result["application"], "Genshin Impact")
        self.assertEqual(result["match_route"], "ai_candidate")
        self.assertEqual(result["skill_state"], "learned")

    def test_genshin_uses_learned_hoyoplay_then_verified_launcher_ui(self):
        launcher = {
            "success": True,
            "completed": True,
            "action": "application_opened",
            "application": "HoYoPlay",
            "skill_state": "reused",
        }
        observed = {
            "status": "game_opened",
            "window": "HoYoPlay",
            "control": "Start Game",
        }
        with patch.object(
            adapters,
            "_launch_start_menu_application",
            return_value=launcher,
        ) as open_launcher, patch.object(
            adapters,
            "_run_hoyoplay_genshin_ui",
            return_value=observed,
        ) as launch_game:
            result = adapters._launch_genshin_through_hoyoplay()
        open_launcher.assert_called_once_with("HoYoPlay")
        launch_game.assert_called_once_with()
        self.assertTrue(result["success"])
        self.assertTrue(result["completed"])
        self.assertEqual(result["action"], "game_opened")
        self.assertEqual(result["game"], "Genshin Impact")
        self.assertEqual(result["launch_route"], "hoyoplay_ui_automation")

    def test_genshin_launcher_never_clicks_without_visible_game_identity(self):
        launcher = {
            "success": True,
            "completed": True,
            "action": "application_opened",
            "application": "HoYoPlay",
            "skill_state": "reused",
        }
        with patch.object(
            adapters,
            "_launch_start_menu_application",
            return_value=launcher,
        ), patch.object(
            adapters,
            "_run_hoyoplay_genshin_ui",
            return_value={"status": "game_identity_not_visible"},
        ):
            result = adapters._launch_genshin_through_hoyoplay()
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])
        self.assertEqual(result["action"], "game_identity_not_visible")

    def test_genshin_visual_fallback_route_is_preserved(self):
        launcher = {
            "success": True,
            "completed": True,
            "action": "application_opened",
            "application": "HoYoPlay",
            "skill_state": "reused",
        }
        observed = {
            "status": "launch_dispatched",
            "window": "HoYoPlay",
            "control": "Start Game",
            "route": "vision_verified_click",
        }
        with patch.object(
            adapters,
            "_launch_start_menu_application",
            return_value=launcher,
        ), patch.object(
            adapters,
            "_run_hoyoplay_genshin_ui",
            return_value=observed,
        ):
            result = adapters._launch_genshin_through_hoyoplay()
        self.assertFalse(result["success"])
        self.assertFalse(result["completed"])
        self.assertTrue(result["needs_clarification"])
        self.assertEqual(result["action"], "game_launch_unverified")
        self.assertEqual(result["launch_route"], "vision_verified_click")

    def test_learned_app_identity_skips_start_menu_discovery(self):
        learned = {
            "name": "Steam",
            "app_id": "steam.app",
            "shortcut_path": r"C:\Start Menu\Steam.lnk",
        }
        with patch.object(adapters.os, "name", "nt"), patch(
            "casper.application_skills.get_application",
            return_value=learned,
        ), patch(
            "casper.application_skills.remember_application",
            return_value=True,
        ) as remember, patch.object(
            adapters,
            "_launch_apps_folder_id",
            return_value=True,
        ) as launch, patch.object(
            adapters.subprocess,
            "run",
        ) as runner:
            result = adapters._launch_start_menu_application("Steam")
        launch.assert_called_once_with("steam.app")
        runner.assert_not_called()
        remember.assert_called_once()
        self.assertEqual(result["launch_route"], "learned_app_id")
        self.assertEqual(result["skill_state"], "reused")

    def test_unresolved_simple_app_never_uses_window_selection_ai(self):
        device_action = Mock()
        fake_device_actions = types.SimpleNamespace(
            execute_user_request=device_action
        )
        with patch.object(
            adapters,
            "_launch_start_menu_application",
            return_value=None,
        ), patch.dict(
            sys.modules,
            {"casper.device_actions": fake_device_actions},
        ):
            search_result, _context = adapters.execute_mode(
                "打开 Steam",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        device_action.assert_not_called()
        self.assertIn("Steam", search_result["direct_reply"])
        self.assertIn("开始菜单应用", search_result["direct_reply"])

    def test_explicit_steam_game_target_is_not_an_application_name(self):
        self.assertEqual(
            adapters._steam_game_target("打开 Steam 里的 FM26"),
            "FM26",
        )
        self.assertEqual(
            adapters._steam_game_target("用 Steam 启动 Football Manager 2026"),
            "Football Manager 2026",
        )
        self.assertEqual(adapters._steam_game_target("打开 Steam"), "")

    def test_steam_library_list_request_is_distinct_from_game_launch(self):
        self.assertTrue(
            adapters._is_steam_library_list_request("看看 Steam 库里有什么？")
        )
        self.assertTrue(
            adapters._is_steam_library_list_request("列出我的 Steam 游戏库")
        )
        self.assertFalse(
            adapters._is_steam_library_list_request("打开 Steam 里的 FM26")
        )
        self.assertEqual(adapters._steam_game_target("看看 Steam 库里有什么"), "")

    def test_steam_library_inventory_hides_local_app_ids(self):
        games = [
            {"name": "Football Manager 2026", "app_id": "123456"},
            {"name": "Another Game", "app_id": "999"},
        ]
        with patch(
            "casper.application_skills.discover_steam_games",
            return_value=games,
        ):
            result = adapters._list_installed_steam_games()
        self.assertEqual(result["action"], "listed_steam_library")
        self.assertEqual(result["total_count"], 2)
        self.assertEqual(
            result["items"],
            [{"name": "Football Manager 2026"}, {"name": "Another Game"}],
        )
        self.assertNotIn("app_id", result["items"][0])

    def test_steam_library_list_never_uses_window_action_ai(self):
        device_action = Mock()
        fake_device_actions = types.SimpleNamespace(
            execute_user_request=device_action
        )
        inventory = {
            "success": True,
            "completed": True,
            "needs_clarification": False,
            "action": "listed_steam_library",
            "application": "Steam",
            "items": [{"name": "Football Manager 2026"}],
            "total_count": 1,
            "truncated": False,
        }
        with patch.object(
            adapters,
            "_list_installed_steam_games",
            return_value=inventory,
        ), patch.dict(
            sys.modules,
            {"casper.device_actions": fake_device_actions},
        ):
            search_result, _context = adapters.execute_mode(
                "看看 Steam 库里有什么",
                {
                    "response_mode": "DEVICE_ACTION",
                    "steam_library_list_selected": True,
                },
                {},
                "",
                lambda _message: None,
            )
        device_action.assert_not_called()
        self.assertIn("1 个已安装游戏", search_result["direct_reply"])
        self.assertIn("Football Manager 2026", search_result["direct_reply"])

    def test_steam_game_launch_uses_installed_manifest_and_learns_alias(self):
        games = [
            {"name": "Football Manager 2026", "app_id": "123456"},
            {"name": "Another Game", "app_id": "999"},
        ]
        selected = games[0]
        with patch.object(adapters.os, "name", "nt"), patch(
            "casper.application_skills.get_steam_game",
            return_value=None,
        ), patch(
            "casper.application_skills.discover_steam_games",
            return_value=games,
        ), patch(
            "casper.application_skills.select_installed_candidate",
            return_value=selected,
        ) as selector, patch(
            "casper.application_skills.remember_steam_game",
            return_value=True,
        ) as remember, patch.object(
            adapters,
            "_dispatch_steam_game",
            return_value=True,
        ) as dispatch:
            result = adapters._launch_steam_game("FM26")
        selector.assert_called_once()
        dispatch.assert_called_once_with("123456")
        remember.assert_called_once()
        self.assertEqual(result["action"], "game_launch_dispatched")
        self.assertEqual(result["game"], "Football Manager 2026")
        self.assertEqual(result["skill_state"], "learned")

    def test_steam_game_request_never_falls_back_to_window_ai(self):
        device_action = Mock()
        fake_device_actions = types.SimpleNamespace(
            execute_user_request=device_action
        )
        with patch.object(
            adapters,
            "_launch_steam_game",
            return_value={
                "success": True,
                "completed": True,
                "needs_clarification": False,
                "action": "game_launch_dispatched",
                "application": "Steam",
                "game": "Football Manager 2026",
                "launch_route": "steam_manifest",
                "skill_state": "learned",
            },
        ), patch.dict(
            sys.modules,
            {"casper.device_actions": fake_device_actions},
        ):
            search_result, _context = adapters.execute_mode(
                "打开 Steam 里的 FM26",
                {
                    "response_mode": "DEVICE_ACTION",
                    "steam_game_launch_selected": True,
                },
                {},
                "",
                lambda _message: None,
            )
        device_action.assert_not_called()
        self.assertEqual(
            search_result["direct_reply"],
            "已让 Steam 启动 Football Manager 2026。",
        )

    def test_product_recommendation_uses_editorial_controller(self):
        expected = {"status": "OK", "cards": [{"title": "Cup"}]}
        with patch.dict(sys.modules, {"tools": types.SimpleNamespace()}), patch.object(
            browser, "product_recommendation_controller", return_value=expected
        ) as recommendation:
            result, _context = adapters.execute_mode(
                "给我推荐三个杯子",
                {
                    "response_mode": "RECOMMENDATION_RESEARCH",
                    "recommendation_domain": "PRODUCT",
                },
                {},
                "",
                lambda _message: None,
            )
        recommendation.assert_called_once()
        self.assertEqual(
            result["evidence_route"], "independent_recommendation_sources"
        )
        self.assertEqual(len(result["cards"]), 1)

    def test_missing_product_domain_is_tagged_on_empty_result(self):
        with patch.dict(sys.modules, {"tools": types.SimpleNamespace()}), patch.object(
            browser, "product_recommendation_controller", return_value=None
        ):
            result, _context = adapters.execute_mode(
                "给我推荐三个杯子",
                {"response_mode": "RECOMMENDATION_RESEARCH"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(result["status"], "NO_RESULT")
        self.assertEqual(result["recommendation_domain"], "PRODUCT")
        self.assertEqual(
            result["evidence_route"], "independent_recommendation_sources"
        )
        self.assertEqual(result["cards"], [])

    def test_product_browser_exception_keeps_fail_closed_route_tag(self):
        with patch.dict(sys.modules, {"tools": types.SimpleNamespace()}), patch.object(
            browser,
            "shopping_research_controller",
            side_effect=RuntimeError("browser failed"),
        ):
            result, _context = adapters.execute_mode(
                "帮我买杯子",
                {"response_mode": "SHOPPING_RESEARCH"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(result["status"], "BROWSER_UNAVAILABLE")
        self.assertEqual(result["recommendation_domain"], "PRODUCT")
        self.assertEqual(result["evidence_route"], "verified_product_pages")
        self.assertEqual(result["cards"], [])

    def test_explicit_purchase_uses_verified_product_controller(self):
        expected = {"status": "OK", "cards": [{"title": "Cup listing"}]}
        with patch.dict(sys.modules, {"tools": types.SimpleNamespace()}), patch.object(
            browser, "shopping_research_controller", return_value=expected
        ) as shopping, patch.object(
            browser, "product_recommendation_controller"
        ) as recommendation:
            result, _context = adapters.execute_mode(
                "查一下这个杯子的价格和库存",
                {
                    "response_mode": "SHOPPING_RESEARCH",
                    "recommendation_domain": "PRODUCT",
                },
                {},
                "",
                lambda _message: None,
            )
        shopping.assert_called_once()
        recommendation.assert_not_called()
        self.assertEqual(result["evidence_route"], "verified_product_pages")
        self.assertEqual(len(result["cards"]), 1)

    def test_folder_only_skill_handoff_has_no_recommendation_cards(self):
        action_result = {
            "success": True,
            "completed": True,
            "action": "folder_skill_awaiting_user_verification",
            "requires_user_verification": True,
            "skill_candidate_id": "candidate-id",
            "target_app": "Football Manager 2026",
            "destination_name": "Football Manager 2026 tactics",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "打开 FM26 战术文件夹",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(search_result["status"], "HUMAN_HANDOFF")
        self.assertEqual(search_result["cards"], [])
        payload = search_result["pending_approval"]["approval_payload"]
        self.assertFalse(payload["recommendations_requested"])

    def test_folder_skill_verification_handoff_keeps_recommendation_cards(self):
        action_result = {
            "success": True,
            "completed": True,
            "action": "tactic_recommendations_awaiting_folder_verification",
            "requires_user_verification": True,
            "skill_candidate_id": "candidate-id",
            "target_app": "Football Manager 2026",
            "destination_name": "Football Manager 2026 tactics",
            "recommendation_count": 3,
            "tactic_page_opened": True,
            "cards": [{"title": "Tactic", "url": "https://tactic.test"}],
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "打开文件夹并推荐战术",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(search_result["status"], "HUMAN_HANDOFF")
        self.assertEqual(len(search_result["cards"]), 1)
        payload = search_result["pending_approval"]["approval_payload"]
        self.assertEqual(payload["verification_kind"], "opened_destination_folder")

    def test_folder_items_are_rendered_once(self):
        result = {
            "folder": "Downloads",
            "items": [
                {"name": "installer.exe", "kind": "file"},
                {"name": "Bekki_Update.zip", "kind": "file"},
                {"name": "Photos", "kind": "folder"},
            ],
        }
        reply = adapters._render_listed_folder(result)
        self.assertIn("Downloads 文件夹里有 3 项", reply)
        self.assertEqual(reply.count("installer.exe"), 1)
        self.assertEqual(reply.count("Bekki_Update.zip"), 1)
        self.assertEqual(reply.count("Photos"), 1)

    def test_empty_folder_has_compact_direct_reply(self):
        reply = adapters._render_listed_folder(
            {"folder": "Downloads", "items": []}
        )
        self.assertEqual(reply, "Downloads 文件夹目前是空的。")

    def test_file_search_renders_only_observed_paths(self):
        reply = adapters._render_file_search(
            {
                "query": "test.txt",
                "scope": ["Desktop", "Documents", "Downloads"],
                "matches": [
                    {
                        "name": "test.txt",
                        "path": r"C:\Users\Main\Documents\test.txt",
                        "kind": "file",
                    }
                ],
                "truncated": False,
            }
        )
        self.assertIn(r"C:\Users\Main\Documents\test.txt", reply)
        self.assertNotIn(r"C:\Users\你的用户名", reply)

    def test_empty_file_search_reports_the_actual_bounded_scope(self):
        reply = adapters._render_file_search(
            {
                "query": "test.txt",
                "scope": ["Desktop", "Documents", "Downloads"],
                "matches": [],
                "truncated": False,
            }
        )
        self.assertIn("Desktop、Documents、Downloads", reply)
        self.assertIn("没有找到", reply)

    def test_recycle_bin_items_are_rendered_once(self):
        reply = adapters._render_recycle_bin(
            {
                "items": [
                    {
                        "name": "old.txt",
                        "original_location": "C:/Users/Test/Desktop",
                        "date_deleted": "2026-08-16",
                    },
                    {"name": "photo.png"},
                ],
                "truncated": False,
            }
        )
        self.assertIn("回收站里有 2 项", reply)
        self.assertEqual(reply.count("old.txt"), 1)
        self.assertEqual(reply.count("photo.png"), 1)

    def test_recycle_restore_handoff_preserves_opaque_approval(self):
        action_result = {
            "success": False,
            "requires_approval": True,
            "approval_type": "recycle_restore",
            "action": "restore_recycle_item",
            "candidate_id": "opaque-item-id",
            "name": "old.txt",
            "original_location": "C:/Users/Test/Desktop",
        }
        plan = {"response_mode": "DEVICE_ACTION"}
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "恢复 old.txt", plan, {}, "", lambda _message: None
            )
        pending = search_result["pending_approval"]
        self.assertEqual(pending["event"], "recycle_restore")
        self.assertEqual(
            pending["approval_payload"]["candidate_id"],
            "opaque-item-id",
        )

    def test_window_control_direct_reply_cannot_claim_file_restore(self):
        reply = adapters._render_window_control(
            {
                "action": "window_control_completed",
                "control": "FOCUS_WINDOW",
                "window": "Microsoft Edge",
            }
        )
        self.assertEqual(reply, "已切换到 Microsoft Edge。")
        self.assertNotIn("恢复文件", reply)

    def test_installed_fm_tactic_has_deterministic_reply(self):
        action_result = {
            "success": True,
            "completed": True,
            "action": "installed_fm_tactic",
            "name": "winner.fmf",
            "destination": "Football Manager 2026 tactics",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "安装战术",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(
            search_result["direct_reply"],
            "已安装 winner.fmf 到 Football Manager 2026 tactics。",
        )

    def test_content_manifest_never_claims_download_or_install(self):
        action_result = {
            "success": True,
            "completed": False,
            "action": "prepared_content_installation_manifest",
            "manifest": {
                "artifact_name": "Community Mod",
                "target_app": "Example Game",
            },
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "找并安装 mod",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        reply = search_result["direct_reply"]
        self.assertIn("Community Mod", reply)
        self.assertIn("尚未下载或安装", reply)

    def test_learned_procedure_becomes_continue_checkpoint(self):
        action_result = {
            "success": True,
            "completed": False,
            "action": "learned_content_skill_candidate",
            "requires_continuation": True,
            "skill_candidate_id": "candidate-id",
            "target_app": "Football Manager 2026",
            "destination_name": "Football Manager 2026 tactics",
            "original_request": "找战术并安装",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "找战术并安装",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(search_result["status"], "HUMAN_HANDOFF")
        pending = search_result["pending_approval"]
        self.assertEqual(pending["handoff_type"], "content_learning_continue")
        self.assertEqual(
            pending["approval_payload"]["skill_candidate_id"], "candidate-id"
        )

    def test_content_browser_verification_becomes_handoff(self):
        action_result = {
            "success": False,
            "completed": False,
            "protected_event": "captcha",
            "reason": "verification",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "网上找并安装 mod",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(search_result["status"], "HUMAN_HANDOFF")
        self.assertEqual(
            search_result["pending_approval"]["handoff_type"],
            "browser_handoff",
        )

    def test_second_stage_browser_handoff_preserves_skill_id(self):
        action_result = {
            "success": False,
            "completed": False,
            "protected_event": "captcha",
            "resume_skill_id": "candidate-id",
            "reason": "verification",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "继续安装战术",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        pending = search_result["pending_approval"]
        self.assertEqual(pending["handoff_type"], "content_browser_handoff")
        self.assertEqual(
            pending["approval_payload"]["skill_id"], "candidate-id"
        )

    def test_first_success_waits_for_user_before_skill_commit(self):
        action_result = {
            "success": True,
            "completed": True,
            "action": "content_installation_awaiting_user_verification",
            "requires_user_verification": True,
            "skill_candidate_id": "candidate-id",
            "target_app": "Football Manager 2026",
            "name": "winner.fmf",
            "destination": "Football Manager 2026 tactics",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "找并安装战术",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(search_result["status"], "HUMAN_HANDOFF")
        pending = search_result["pending_approval"]
        self.assertEqual(pending["handoff_type"], "skill_user_verification")
        self.assertEqual(
            pending["approval_payload"]["skill_candidate_id"], "candidate-id"
        )

    def test_device_clarification_is_rendered_without_model_rewrite(self):
        action_result = {
            "success": False,
            "needs_clarification": True,
            "clarification": "搜索结果与目标游戏内容无关。",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "找战术",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(
            search_result["direct_reply"],
            "搜索结果与目标游戏内容无关。",
        )

    def test_retryable_content_failure_restores_continue_checkpoint(self):
        action_result = {
            "success": False,
            "needs_clarification": True,
            "clarification": "没有找到下载链接。",
            "content_installation_retry_available": True,
            "resume_skill_id": "candidate-id",
            "target_app": "Football Manager 26",
            "destination_name": "Football Manager 26 tactics",
            "original_request": "找战术并安装",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "找战术并安装",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(search_result["status"], "HUMAN_HANDOFF")
        pending = search_result["pending_approval"]
        self.assertEqual(pending["event"], "content_installation_retry")
        self.assertEqual(
            pending["approval_payload"]["skill_candidate_id"],
            "candidate-id",
        )

    def test_exact_resume_terminal_result_requests_checkpoint_clear(self):
        action_result = {
            "success": False,
            "completed": False,
            "needs_clarification": True,
            "clarification": "之前的临时技能已经不存在。",
            "exact_resume_terminal": True,
            "resume_skill_id": "candidate-missing",
        }
        plan = {
            "response_mode": "DEVICE_ACTION",
            "content_resume_skill_id": "candidate-missing",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "找战术并安装", plan, {}, "", lambda _message: None
            )

        self.assertTrue(search_result["clear_exact_resume_checkpoint"])
        self.assertNotEqual(search_result.get("status"), "HUMAN_HANDOFF")

    def test_exact_resume_direct_success_consumes_old_checkpoint(self):
        action_result = {
            "success": True,
            "completed": True,
            "action": "installed_fm_tactic",
            "name": "winner.fmf",
            "destination": "Football Manager 2026 tactics",
        }
        plan = {
            "response_mode": "DEVICE_ACTION",
            "content_resume_skill_id": "skill-verified",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "找战术并安装", plan, {}, "", lambda _message: None
            )

        self.assertTrue(search_result["exact_resume_completed"])

    def test_exact_resume_retry_handoff_does_not_consume_checkpoint_directly(self):
        action_result = {
            "success": False,
            "needs_clarification": True,
            "clarification": "前置阶段暂时失败。",
            "content_installation_retry_available": True,
            "resume_skill_id": "candidate-id",
            "original_request": "找战术并安装",
        }
        plan = {
            "response_mode": "DEVICE_ACTION",
            "content_resume_skill_id": "candidate-id",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "找战术并安装", plan, {}, "", lambda _message: None
            )

        self.assertEqual(search_result["status"], "HUMAN_HANDOFF")
        self.assertNotIn("exact_resume_completed", search_result)
        self.assertNotIn("clear_exact_resume_checkpoint", search_result)

    def test_file_device_scope_is_forwarded_to_bounded_file_workflow(self):
        action_result = {
            "success": True,
            "completed": True,
            "action": "searched_files",
            "query": "bekki_search_test.txt",
            "matches": ["C:/Users/Main/Downloads/bekki_search_test.txt"],
        }
        plan = {
            "response_mode": "DEVICE_ACTION",
            "device_scope": "FILE_ACTION",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ) as execute:
            adapters.execute_mode(
                "查找 bekki_search_test.txt",
                plan,
                {},
                "",
                lambda _message: None,
            )
        self.assertTrue(execute.call_args.kwargs["file_workflow_selected"])

    def test_xiaohongshu_social_plan_calls_only_social_controller(self):
        expected = {
            "status": "OK",
            "query": "Arcadia 亲子餐厅",
            "results": [],
            "context": "visible Xiaohongshu discussion",
        }
        plan = {
            "response_mode": "SOCIAL_RESEARCH",
            "social_platforms": ["xiaohongshu"],
        }
        with patch(
            "tools.social_research_controller",
            return_value=expected,
        ) as social, patch(
            "tools.search_controller",
        ) as generic_search:
            result, _context = adapters.execute_mode(
                "去小红书搜索 Arcadia 亲子餐厅",
                plan,
                {},
                "",
                lambda _message: None,
            )
        social.assert_called_once()
        self.assertEqual(
            social.call_args.args[:2],
            (
                "去小红书搜索 Arcadia 亲子餐厅",
                ["xiaohongshu"],
            ),
        )
        generic_search.assert_not_called()
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
