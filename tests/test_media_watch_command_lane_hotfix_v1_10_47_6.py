from pathlib import Path
import unittest
from unittest.mock import patch

import magi
import media_watch
import melchior


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


def _command_route():
    return {
        "lane": "COMMAND",
        "confidence": 1.0,
        "reason": "The user asked an external service to play media.",
        "social_scope": "OTHER",
        "social_platforms": [],
        "search_scope": "OTHER",
        "recommendation_domain": None,
        "local_knowledge_sufficiency": "NONE",
        "source": "ai_primary",
    }


class MediaWatchDiscoveryBoundaryTests(unittest.TestCase):
    def test_named_and_random_media_discovery_are_detected(self):
        for message in (
            "去iyf.tv播放名侦探柯南",
            "我想看《名侦探柯南》",
            "去B站找一个下饭视频",
            "在 YouTube 播放 aespa MV",
            "play Detective Conan on iyf.tv",
        ):
            with self.subTest(message=message):
                self.assertTrue(
                    media_watch.looks_like_media_discovery_request(message)
                )

    def test_active_player_controls_and_social_search_stay_out(self):
        for message in (
            "暂停视频",
            "继续播放",
            "把声音调大一点",
            "播放下一集",
            "播放第28集",
            "播放这个视频",
            "打开iyf.tv",
            "去B站搜索aespa最近的视频",
            "总结这个视频讲了什么",
            "我想看看我有哪些提醒",
            "我想看账户余额",
            "find a stroller on amazon.com",
            "play Genshin Impact",
        ):
            with self.subTest(message=message):
                self.assertFalse(
                    media_watch.looks_like_media_discovery_request(message)
                )


class MediaWatchCommandLaneRepairTests(unittest.TestCase):
    def test_command_route_is_repaired_to_media_watch(self):
        route = magi.reconcile_media_watch_route(
            "去iyf.tv播放名侦探柯南",
            _command_route(),
        )
        self.assertEqual(route["lane"], "SEARCH")
        self.assertEqual(route["search_scope"], "MEDIA_WATCH")
        self.assertEqual(route["social_scope"], "OTHER")
        self.assertEqual(route["social_platforms"], [])
        self.assertIsNone(route["recommendation_domain"])

    def test_initial_magi_gate_reconciles_model_command_mistake(self):
        with patch.object(magi, "_run_gate", return_value=_command_route()):
            route = magi.route_request("去iyf.tv播放名侦探柯南")
        self.assertEqual(route["lane"], "SEARCH")
        self.assertEqual(route["search_scope"], "MEDIA_WATCH")

    def test_real_gate_path_logs_and_returns_the_repaired_contract(self):
        raw = dict(_command_route())
        raw.pop("source", None)
        with patch.object(
            magi.tools,
            "run_ai_prompt",
            return_value=raw,
        ), patch.object(magi.tools, "unload_model", return_value=True):
            route = magi.route_request("去iyf.tv播放名侦探柯南")
        self.assertEqual(route["lane"], "SEARCH")
        self.assertEqual(route["search_scope"], "MEDIA_WATCH")
        self.assertTrue(route["source"].endswith("_watch_contract"))

    def test_magi_lane_audit_cannot_reintroduce_command_mistake(self):
        with patch.object(magi, "_run_gate", return_value=_command_route()):
            route = magi.audit_route(
                "去iyf.tv播放名侦探柯南",
                previous_route=_command_route(),
                downstream_mode="MEDIA_WATCH",
            )
        self.assertEqual(route["lane"], "SEARCH")
        self.assertEqual(route["search_scope"], "MEDIA_WATCH")

    def test_melchior_defends_against_a_legacy_command_route(self):
        with patch.object(
            melchior.tools,
            "run_ai_prompt",
            side_effect=AssertionError("media contract must bypass router AI"),
        ) as model:
            plan = melchior.plan_request(
                "去iyf.tv播放名侦探柯南",
                magi_route=_command_route(),
            )
        model.assert_not_called()
        self.assertEqual(plan["response_mode"], "MEDIA_WATCH")
        self.assertEqual(plan["magi_lane"], "SEARCH")

    def test_prompts_distinguish_discovery_from_active_controls(self):
        for relative in (
            "prompts/magi_gate.txt",
            "prompts/magi_audit.txt",
            "prompts/melchior_router.txt",
            "prompts/melchior_lane_recover.txt",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("iyf.tv", source)
            self.assertIn("暂停", source)

    def test_build_id_is_current(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('BEKKI_BUILD_ID = "' + BUILD_ID + '"', source)


if __name__ == "__main__":
    unittest.main()
