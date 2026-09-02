import ast
from pathlib import Path
import unittest
from unittest.mock import patch

import magi
import melchior
import tools
from casper import adapters
from casper import browser as casper_browser


ROOT = Path(__file__).resolve().parents[1]


def _discussion_route():
    return {
        "lane": "SEARCH",
        "confidence": 0.98,
        "reason": "The open causal clause requires a cross-site roundup.",
        "social_scope": "OTHER",
        "social_platforms": [],
        "search_scope": "DISCUSSION_FEED",
        "recommendation_domain": None,
        "local_knowledge_sufficiency": "NONE",
    }


class DiscussionRoutingV110418Tests(unittest.TestCase):
    def test_magi_accepts_discussion_feed_contract(self):
        route = magi._valid_ai_route(_discussion_route())
        self.assertIsNotNone(route)
        self.assertEqual(route["search_scope"], "DISCUSSION_FEED")
        self.assertEqual(route["social_scope"], "OTHER")
        self.assertEqual(route["social_platforms"], [])

    def test_exact_mixed_question_is_an_explicit_prompt_example(self):
        gate = (ROOT / "prompts" / "magi_gate.txt").read_text(encoding="utf-8")
        router = (ROOT / "prompts" / "melchior_router.txt").read_text(
            encoding="utf-8"
        )
        for prompt in (gate, router):
            self.assertIn("卡黄闹翻了吗？", prompt)
            self.assertIn("卡黄是闹翻了吗", prompt)
            self.assertIn("DISCUSSION_FEED", prompt)
            self.assertIn("CLAIM_CHECK", prompt)

    def test_authoritative_discussion_plan_never_uses_357(self):
        plan = melchior._authoritative_discussion_plan(_discussion_route())
        self.assertEqual(plan["response_mode"], "DISCUSSION_FEED")
        self.assertEqual(plan["research_depth"], "discussion_roundup")
        self.assertEqual(plan["source_policy"], "discussion_sources")
        self.assertNotEqual(plan["research_depth"], "3_5_7")
        self.assertEqual(plan["social_platforms"], [])

    def test_plan_request_honors_magi_discussion_without_compact_drift(self):
        with patch.object(
            melchior.tools,
            "run_ai_prompt",
            side_effect=AssertionError("authoritative discussion route must bypass"),
        ) as model:
            plan = melchior.plan_request(
                "卡黄是闹翻了吗，她们为什么会闹翻？",
                magi_route=_discussion_route(),
            )
        model.assert_not_called()
        self.assertEqual(plan["response_mode"], "DISCUSSION_FEED")

    def test_empty_native_social_plan_recovers_to_discussion_scope(self):
        plan = melchior._normalize_plan(
            {"response_mode": "SOCIAL_RESEARCH", "social_platforms": []}
        )
        result = melchior._reconcile_platformless_social_plan(
            plan,
            _discussion_route(),
            "总结知乎和贴吧里对这件事的不同说法",
        )
        self.assertEqual(result["response_mode"], "DISCUSSION_FEED")
        self.assertEqual(result["social_platforms"], [])

    def test_named_supported_platform_remains_native_social(self):
        plan = melchior._normalize_plan(
            {
                "response_mode": "SOCIAL_RESEARCH",
                "social_platforms": ["bilibili"],
            }
        )
        result = melchior._reconcile_platformless_social_plan(
            plan,
            _discussion_route(),
            "在 B 站搜卡黄为什么闹翻",
        )
        self.assertEqual(result["response_mode"], "SOCIAL_RESEARCH")
        self.assertEqual(result["social_platforms"], ["bilibili"])

    def test_unsupported_discussion_sites_are_not_native_platforms(self):
        prompt = (ROOT / "prompts" / "magi_gate.txt").read_text(encoding="utf-8")
        for site in ("Zhihu", "Quora", "Tieba"):
            self.assertIn(site, prompt)
        self.assertIn("social_platforms []", prompt)


class DiscussionExecutionV110418Tests(unittest.TestCase):
    def test_adapter_dispatches_to_dedicated_controller(self):
        plan = {
            "response_mode": "DISCUSSION_FEED",
            "risk": "low",
            "complexity": "medium",
        }
        expected = {"status": "OK", "feed": [{"summary": "x"}], "cards": []}
        with patch.object(
            tools,
            "build_discussion_queries",
            return_value=["q1", "q2"],
        ), patch.object(
            tools,
            "unload_model",
            return_value=True,
        ), patch.object(
            casper_browser,
            "discussion_feed_controller",
            return_value=expected,
        ) as controller:
            result, _context = adapters.execute_mode(
                "为什么会这样？",
                plan,
                {},
                "",
                lambda _value: None,
            )
        self.assertEqual(result, expected)
        controller.assert_called_once()

    def test_controller_returns_attributed_article_cards_not_news(self):
        candidates = [
            {
                "title": "讨论一",
                "description": "观点一",
                "url": "https://example.com/thread-1",
                "domain": "example.com",
                "published": "",
            },
            {
                "title": "讨论二",
                "description": "观点二",
                "url": "https://forum.example.org/thread-2",
                "domain": "forum.example.org",
                "published": "",
            },
        ]
        extracted = [
            {
                "source_index": index,
                "source_title": source["title"],
                "domain": source["domain"],
                "url": source["url"],
                "published_at": "",
                "source_kind": "FORUM_THREAD",
                "summary": "该来源提出一种解释。",
                "claims": ["这只是该来源的解释。"],
                "evidence_quote": "",
                "stance": "EXPLAINS_CONTEXT",
                "perspective_key": "互动变化",
                "uncertainty": "未独立证实。",
                "relevance_score": 90 - index,
                "reason": "直接相关",
                "evidence_level": "opened_page",
                "image_url": "",
            }
            for index, source in enumerate(candidates, start=1)
        ]
        with patch.object(
            casper_browser,
            "discover_web",
            return_value={"status": "OK", "results": candidates},
        ), patch.object(
            casper_browser,
            "_select_discussion_sources",
            return_value=candidates,
        ), patch.object(
            casper_browser,
            "read_url",
            return_value={
                "success": True,
                "content": "可读正文",
                "error": None,
                "image_url": "",
                "published": "",
            },
        ), patch.object(
            casper_browser,
            "_extract_discussion_sources",
            return_value=extracted,
        ), patch.object(
            casper_browser,
            "_synthesize_discussion_feed",
            return_value="这批讨论不能单独证实前提，但主要有两类解释。",
        ):
            result = casper_browser.discussion_feed_controller(
                ["q1"],
                user_request="卡黄是闹翻了吗，她们为什么会闹翻？",
                status_callback=lambda _value: None,
            )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(result["cards"]), 2)
        self.assertTrue(all(card["type"] == "article" for card in result["cards"]))
        self.assertTrue(all(item["content_type"] == "DISCUSSION" for item in result["results"]))
        self.assertTrue(all(item["is_concrete_news"] is False for item in result["results"]))
        self.assertIn("卡片", result["direct_reply"])

    def test_discussion_prompts_keep_claims_attributed(self):
        extract = (ROOT / "prompts" / "casper_discussion_extract.txt").read_text(
            encoding="utf-8"
        )
        synthesis = (
            ROOT / "prompts" / "casper_discussion_synthesis.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("Repetition across pages is not confirmation", extract)
        self.assertIn("not NEWS_FEED and not CLAIM_CHECK", synthesis)
        self.assertIn("discussion repetition alone", synthesis)

    def test_prompt_and_code_mirrors_match(self):
        pairs = [
            ("melchior.py", "casper/melchior.py"),
            ("tools.py", "casper/tools.py"),
            ("prompts/discussion_query.txt", "casper/prompts/discussion_query.txt"),
            (
                "prompts/casper_discussion_extract.txt",
                "casper/prompts/casper_discussion_extract.txt",
            ),
            (
                "prompts/casper_discussion_synthesis.txt",
                "casper/prompts/casper_discussion_synthesis.txt",
            ),
        ]
        for left, right in pairs:
            with self.subTest(left=left):
                self.assertEqual(
                    (ROOT / left).read_text(encoding="utf-8"),
                    (ROOT / right).read_text(encoding="utf-8"),
                )


class DiscussionFailureBoundaryV110418Tests(unittest.TestCase):
    def test_no_discussion_evidence_cannot_become_a_rumor_verdict(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        node = next(
            value for value in tree.body
            if isinstance(value, ast.FunctionDef)
            and value.name == "_discussion_feed_failure_reply"
        )
        namespace = {}
        exec(
            compile(ast.fix_missing_locations(ast.Module([node], [])), "main.py", "exec"),
            namespace,
        )
        reply = namespace["_discussion_feed_failure_reply"](
            {"status": "NO_RELEVANT_DISCUSSION", "feed": []}
        )
        self.assertIn("不能总结", reply)
        self.assertIn("零条讨论", reply)


if __name__ == "__main__":
    unittest.main()
