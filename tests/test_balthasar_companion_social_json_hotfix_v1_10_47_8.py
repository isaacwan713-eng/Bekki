import base64
import json
from pathlib import Path
from unittest import mock
import unittest

import balthasar
import companion_watch
import tools


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"


def valid_frame():
    return base64.b64encode(b"frame" * 140).decode("ascii")


def social_item(index):
    return {
        "title": f"夜蝶视频 {index}",
        "author": f"作者 {index}",
        "time": "2025-02-02",
        "engagement": "99.7万 1776",
        "relevance_score": 95,
        "relevance_reason": "标题直接包含夜蝶。",
        "kind": "other",
    }


class BalthasarCompanionHotfixTests(unittest.TestCase):
    def test_auto_reactions_get_zero_latency_rotating_balthasar_direction(self):
        with mock.patch.object(balthasar.tools, "run_ai_prompt") as model:
            first = balthasar.plan_companion_watch(
                "AUTO_REACTION", "", [], '{"mood":"playful","closeness":0.3}',
                reaction_index=0,
                model_name="gemma4:e4b",
            )
            second = balthasar.plan_companion_watch(
                "AUTO_REACTION", "", [], '{"mood":"playful","closeness":0.3}',
                reaction_index=1,
                model_name="gemma4:e4b",
            )
        model.assert_not_called()
        self.assertEqual(first["tone"], "playful")
        self.assertEqual(first["familiarity"], "familiar")
        self.assertNotEqual(first["social_move"], second["social_move"])
        self.assertNotEqual(first["cadence"], second["cadence"])

    def test_user_message_uses_same_response_model_for_balthasar_plan(self):
        planned = {
            **balthasar.DEFAULT_PLAN,
            "user_emotion": "excited",
            "intensity": 0.7,
            "tone": "playful",
            "support_style": "celebrating",
            "bekki_mood": "excited",
            "energy_delta": 0.03,
            "closeness_delta": 0.004,
            "social_move": "emotional_echo",
            "cadence": "two_beat",
            "expressiveness": "high",
            "familiarity": "familiar",
            "question_policy": "none",
            "reason": "The user explicitly sounds excited.",
        }
        with mock.patch.object(
            balthasar.tools,
            "run_ai_prompt",
            return_value=planned,
        ) as model:
            result = balthasar.plan_companion_watch(
                "USER_MESSAGE",
                "这段也太燃了吧",
                [{"role": "YOU", "text": "快看"}],
                '{"mood":"curious","closeness":0.3}',
                model_name="gemma4:12b",
            )
        self.assertEqual(result["social_move"], "emotional_echo")
        self.assertEqual(model.call_args.args[0], "prompts/balthasar_companion_watch.txt")
        self.assertEqual(model.call_args.kwargs["model_name"], "gemma4:12b")
        self.assertEqual(model.call_args.kwargs["num_ctx"], 2048)

    def test_companion_prompt_receives_balthasar_without_rewriting_evidence(self):
        payload = {
            "request_kind": "AUTO_REACTION",
            "image_base64": valid_frame(),
            "video_title": "夜蝶",
            "platform": "bilibili",
            "video_url": "https://www.bilibili.com/video/BV12s411Q7k1",
            "generation": 9,
            "reaction_index": 2,
            "history": [{"role": "BEKKI", "text": "刚才那个转场很帅"}],
        }
        plan = {
            **balthasar.DEFAULT_COMPANION_PLAN,
            "tone": "playful",
            "social_move": "playful_tease",
            "cadence": "two_beat",
        }
        answer = json.dumps(
            {
                "reply": "这个眼神一出来，气场立刻变了。",
                "should_show": True,
                "response_kind": "REACTION",
            },
            ensure_ascii=False,
        )
        with mock.patch.object(
            companion_watch.balthasar,
            "plan_companion_watch",
            return_value=plan,
        ), mock.patch.object(
            companion_watch.model_runtime,
            "generate",
            return_value=answer,
        ) as generate:
            result = companion_watch.generate_reply(
                payload,
                emotion_context='{"mood":"playful","closeness":0.3}',
            )
        prompt = generate.call_args.args[0]
        self.assertIn("Balthasar companion direction", prompt)
        self.assertIn('"social_move":"playful_tease"', prompt)
        self.assertIn("not a visual-caption service", prompt)
        self.assertIn("never overrides visible", prompt)
        self.assertEqual(result["reply"], "这个眼神一出来，气场立刻变了。")
        self.assertEqual(result["_balthasar_plan"], plan)

    def test_stock_or_duplicate_auto_reaction_is_silenced(self):
        generic = companion_watch.normalize_response(
            {
                "reply": "这一幕很有意思～",
                "should_show": True,
                "response_kind": "REACTION",
            },
            "AUTO_REACTION",
            history=[],
        )
        duplicate = companion_watch.normalize_response(
            {
                "reply": "这个眼神一出来，气场立刻变了！",
                "should_show": True,
                "response_kind": "REACTION",
            },
            "AUTO_REACTION",
            history=[{"role": "BEKKI", "text": "这个眼神一出来，气场立刻变了。"}],
        )
        self.assertFalse(generic["should_show"])
        self.assertFalse(duplicate["should_show"])

    def test_main_applies_only_user_authored_companion_emotion(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        worker = source[source.index("def _run_companion_watch"):source.index(
            "def request_companion_watch"
        )]
        self.assertIn("emotion.prompt_context(emotion_state)", worker)
        self.assertIn('== "USER_MESSAGE"', worker)
        self.assertIn("emotion.apply_balthasar_plan", worker)


class SocialJsonRecoveryHotfixTests(unittest.TestCase):
    def test_truncated_social_array_keeps_all_closed_items(self):
        raw = (
            '{"page_summary":"夜蝶相关视频","recent_post_count":3,"items":['
            + json.dumps(social_item(1), ensure_ascii=False)
            + ","
            + json.dumps(social_item(2), ensure_ascii=False)
            + ',{"title":"中日字幕雄蕊雌蕊000000'
        )
        recovered = tools._recover_complete_social_evidence(raw)
        self.assertEqual(
            [item["title"] for item in recovered["items"]],
            ["夜蝶视频 1", "夜蝶视频 2"],
        )
        self.assertEqual(recovered["page_summary"], "夜蝶相关视频")
        self.assertTrue(recovered["_partial_json_recovery"])

    def test_extract_social_evidence_uses_structural_recovery(self):
        raw = (
            '{"page_summary":"夜蝶相关视频","recent_post_count":2,"items":['
            + json.dumps(social_item(1), ensure_ascii=False)
            + ',{"title":"截断'
        )
        with mock.patch.object(tools, "call_model", return_value=raw):
            evidence = tools.extract_social_evidence(
                "可见页面文字",
                current_date="2026-09-02",
                selection_mode="RELEVANCE",
                user_message="去 Bilibili 搜索夜蝶",
                query="夜蝶",
                platforms=["bilibili"],
            )
        self.assertEqual(len(evidence["items"]), 1)
        self.assertEqual(evidence["items"][0]["title"], "夜蝶视频 1")
        self.assertIn("已保留截断前完整读取", " ".join(evidence["warnings"]))

    def test_recovered_bilibili_item_reaches_a_card_in_controller(self):
        item = social_item(1)
        raw = (
            '{"page_summary":"夜蝶相关视频","recent_post_count":2,"items":['
            + json.dumps(item, ensure_ascii=False)
            + ',{"title":"中日字幕雄蕊雌蕊000000'
        )
        candidate = {
            "platform": "bilibili",
            "url": "https://www.bilibili.com/video/BV12s411Q7k1/",
            "visible_text": "夜蝶视频 1 作者 1 99.7万 1776",
            "image_url": "https://i0.hdslb.com/bfs/archive/night.jpg",
            "post_title": "夜蝶视频 1",
        }
        detail = {
            **candidate,
            "search_visible_text": candidate["visible_text"],
            "visual_frame": "",
        }
        with mock.patch.object(
            tools,
            "build_social_query_plan",
            return_value={
                "query": "夜蝶",
                "selection_mode": "RELEVANCE",
                "recency_days": None,
                "ranking_mode": "DEFAULT",
                "fallback_query": None,
            },
        ), mock.patch.object(tools.time, "sleep", return_value=None), mock.patch.object(
            tools, "call_model", return_value=raw
        ), mock.patch.object(
            tools.social_browser,
            "open_social_search",
            return_value={"url": "https://search.bilibili.com/all?keyword=x"},
        ), mock.patch.object(
            tools.social_browser,
            "inspect_active_social_page",
            return_value={
                "url": "https://search.bilibili.com/all?keyword=x",
                "visible_text": candidate["visible_text"],
                "visual_frames": [],
                "post_candidates": [candidate],
            },
        ), mock.patch.object(
            tools.social_browser,
            "resolve_social_post_targets",
            return_value=[candidate],
        ), mock.patch.object(
            tools.social_browser,
            "inspect_social_post_details",
            return_value=[detail],
        ), mock.patch.object(
            tools.social_browser, "close_social_browser"
        ), mock.patch.object(
            tools, "extract_social_post_introductions", return_value=[]
        ), mock.patch.object(
            tools, "synthesize_social_research_reply", return_value="找到相关夜蝶视频。"
        ):
            result = tools.social_research_controller(
                "去 Bilibili 搜索夜蝶",
                ["bilibili"],
            )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(result["cards"][0]["title"], "夜蝶视频 1")

    def test_social_schema_bounds_runaway_strings_and_mirrors_match(self):
        schema = tools._SOCIAL_EVIDENCE_SCHEMA
        item = schema["properties"]["items"]["items"]["properties"]
        self.assertEqual(item["title"]["maxLength"], 300)
        self.assertEqual(schema["properties"]["warnings"]["maxItems"], 6)
        self.assertEqual(
            (ROOT / "tools.py").read_bytes(),
            (ROOT / "casper" / "tools.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "prompts" / "social_extract.txt").read_bytes(),
            (ROOT / "casper" / "prompts" / "social_extract.txt").read_bytes(),
        )

    def test_build_identity_and_new_balthasar_prompt_are_packaged(self):
        metadata = json.loads((ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertIn(
            f'BEKKI_BUILD_ID = "{BUILD_ID}"',
            (ROOT / "main.py").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            (ROOT / "prompts" / "balthasar_companion_watch.txt").read_bytes(),
            (
                ROOT / "casper" / "prompts" / "balthasar_companion_watch.txt"
            ).read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
