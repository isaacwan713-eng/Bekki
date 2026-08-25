import ast
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from casper import browser


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def function_source(path, name):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    return ast.unparse(node), node


class ResearchModelBudgetTests(unittest.TestCase):
    def test_fact_scope_prompts_classify_yesterday_as_explicit_period(self):
        prompt_root = PROJECT_ROOT / "prompts"
        for name in ("fact_intent_scope.txt", "fact_intent_scope_retry.txt"):
            text = (prompt_root / name).read_text(encoding="utf-8")
            self.assertIn("EXPLICIT_PERIOD", text)
            self.assertIn("Yesterday", text.replace("yesterday", "Yesterday"))

    def test_fact_scope_reconciles_yesterday_schema_contradiction(self):
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(return_value={
                "scope_type": "CURRENT_ACTIVE_STATE",
                "requested_period": "Yesterday's game",
                "allow_previous_period": False,
                "reason": "specific past day",
            })
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._plan_fact_intent_scope(
                "道奇昨天赢了吗",
                "Los Angeles Dodgers August 19 final score",
            )
        self.assertEqual(result["scope_type"], "EXPLICIT_PERIOD")

    def test_light_persona_preserves_names_and_avoids_duplicate_translation(self):
        prompt = (PROJECT_ROOT / "prompts" / "bekki_persona_light.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("Preserve proper names", prompt)
        self.assertIn("Do not append an English duplicate", prompt)

    def test_final_parser_accepts_markdown_fenced_json(self):
        _source, function = function_source(PROJECT_ROOT / "main.py", "parse_ai_result")
        namespace = {"json": json, "print": lambda *args: None}
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "main.py", "exec"),
            namespace,
        )
        value, error = namespace["parse_ai_result"](
            '```json\n{"reply":"有新闻","highlights":[]}\n```'
        )
        self.assertIsNone(error)
        self.assertEqual(value["reply"], "有新闻")

    def test_news_extract_and_curation_use_12b_without_thinking(self):
        extract_source, _ = function_source(
            PROJECT_ROOT / "casper" / "browser.py", "_extract_news_events"
        )
        curate_source, _ = function_source(
            PROJECT_ROOT / "casper" / "browser.py", "_curate_news_feed"
        )
        for source in (extract_source, curate_source):
            self.assertIn("model_name='gemma3:12b'", source)
            self.assertIn("think=False", source)
            self.assertNotIn("gpt-oss:20b", source)
        self.assertNotIn("32768", extract_source)
        self.assertIn("articles[:6]", extract_source)

    def test_news_extractor_runtime_call_has_bounded_12b_contract(self):
        result = {
            "items": [{
                "index": 1,
                "is_concrete_news": True,
                "content_type": "NEWS",
                "event_title": "Match result",
                "summary": "Manchester United won.",
                "published_at": "2026-08-20",
                "event_date": "2026-08-20",
                "event_key": "match-result",
                "uncertainty": "",
                "relevance_score": 90,
                "reason": "Concrete event.",
            }]
        }
        fake_tools = types.SimpleNamespace(run_ai_prompt=Mock(return_value=result))
        articles = [{
            "title": "Match result",
            "description": "Manchester United won.",
            "domain": "news.example",
            "url": "https://news.example/match",
            "published": "2026-08-20",
            "source_score": 90,
            "page_success": True,
            "page_content": "Article body",
        }]
        with patch.dict(sys.modules, {"tools": fake_tools}):
            decisions = browser._extract_news_events("Manchester United news", articles)
        self.assertTrue(decisions[1]["is_concrete_news"])
        kwargs = fake_tools.run_ai_prompt.call_args.kwargs
        self.assertEqual(kwargs["model_name"], "gemma3:12b")
        self.assertFalse(kwargs["think"])
        self.assertLessEqual(kwargs["num_ctx"], 12288)

    def test_news_extractor_keeps_partial_rows_and_recovers_union_label(self):
        result = {
            "items": [{
                "index": 1,
                "is_concrete_news": True,
                "content_type": "NEWS | AGGREGATOR",
                "event_title": "Club announcement",
                "summary": "Manchester United announced an update.",
                "published_at": "2026-08-20",
                "event_date": "2026-08-20",
                "event_key": "club-update",
                "uncertainty": "",
                "relevance_score": 88,
                "reason": "Concrete current announcement.",
            }]
        }
        fake_tools = types.SimpleNamespace(run_ai_prompt=Mock(return_value=result))
        articles = [
            {
                "title": "Club announcement",
                "description": "Manchester United announced an update.",
                "domain": "manutd.com",
                "url": "https://manutd.com/update",
                "published": "",
                "source_score": 95,
                "page_success": True,
                "page_content": "Article body",
            },
            {
                "title": "Unclassified sixth page",
                "description": "The compact model omitted this row.",
                "domain": "example.com",
                "url": "https://example.com/omitted",
                "published": "",
                "source_score": 50,
                "page_success": True,
                "page_content": "Page body",
            },
        ]
        with patch.dict(sys.modules, {"tools": fake_tools}):
            decisions = browser._extract_news_events("Manchester United news", articles)
        self.assertEqual(set(decisions), {1})
        self.assertEqual(decisions[1]["content_type"], "NEWS")
        self.assertTrue(decisions[1]["is_concrete_news"])

    def test_news_controller_has_nonempty_curation_fallback(self):
        source, _ = function_source(
            PROJECT_ROOT / "casper" / "browser.py", "news_feed_controller"
        )
        self.assertIn("if not selected", source)
        self.assertIn("if item.get('is_concrete_news')", source)
        self.assertIn("Missing per-source AI decision", source)

    def test_news_curation_deduplicates_identical_event_keys(self):
        selected = {
            "selected": [
                {"source_index": 1, "reason": "official preview"},
                {"source_index": 2, "reason": "second publisher"},
                {"source_index": 3, "reason": "different event"},
            ]
        }
        fake_tools = types.SimpleNamespace(run_ai_prompt=Mock(return_value=selected))
        articles = [
            {
                "is_concrete_news": True,
                "event_title": "Team news for Hull opener",
                "event_summary": "Official team news.",
                "event_key": "Man Utd vs Hull City",
                "domain": "manutd.com",
            },
            {
                "is_concrete_news": True,
                "event_title": "Injury boost before Hull",
                "event_summary": "A second report on the same team news.",
                "event_key": "Man Utd vs Hull City",
                "domain": "example.com",
            },
            {
                "is_concrete_news": True,
                "event_title": "Transfer update",
                "event_summary": "A separate transfer event.",
                "event_key": "Man Utd transfer",
                "domain": "example.net",
            },
        ]
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._curate_news_feed("latest news", articles)
        self.assertEqual(result, [1, 3])

    def test_news_controller_returns_valid_rows_when_one_source_is_omitted(self):
        candidates = [
            {
                "title": "Club announcement",
                "description": "Manchester United announced an update.",
                "domain": "manutd.com",
                "url": "https://manutd.com/update",
                "published": "",
                "source_score": 95,
            },
            {
                "title": "Unclassified page",
                "description": "This row is omitted by the extractor.",
                "domain": "example.com",
                "url": "https://example.com/omitted",
                "published": "",
                "source_score": 50,
            },
        ]
        decisions = {
            1: {
                "is_concrete_news": True,
                "content_type": "NEWS",
                "event_title": "Club announcement",
                "summary": "Manchester United announced an update.",
                "published_at": "2026-08-20",
                "event_date": "2026-08-20",
                "event_key": "club-update",
                "uncertainty": "",
                "relevance_score": 88,
                "reason": "Concrete current announcement.",
            }
        }
        fake_tools = types.SimpleNamespace(
            score_sources=Mock(return_value=candidates)
        )
        fake_cards = types.SimpleNamespace(clean_cards=lambda values: list(values))
        with patch.dict(
            sys.modules,
            {"tools": fake_tools, "result_cards": fake_cards},
        ), patch.object(
            browser,
            "discover_web",
            return_value={"status": "OK", "results": candidates},
        ), patch.object(
            browser,
            "read_url",
            return_value={"success": True, "content": "Article body"},
        ), patch.object(
            browser,
            "_extract_news_events",
            return_value=decisions,
        ), patch.object(
            browser,
            "_curate_news_feed",
            return_value=[],
        ):
            result = browser.news_feed_controller(
                ["Manchester United latest news"],
                user_request="给我看看最新的曼联新闻",
            )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(result["feed"]), 1)
        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(result["feed"][0]["title"], "Club announcement")

    def test_query_and_consensus_helpers_use_12b_in_both_mirrors(self):
        helper_names = (
            "build_search_query",
            "build_news_queries",
            "build_claim_query",
            "find_consensus",
            "rank_news_results",
        )
        for relative in ("tools.py", "casper/tools.py"):
            for name in helper_names:
                source, _ = function_source(PROJECT_ROOT / relative, name)
                with self.subTest(file=relative, function=name):
                    self.assertIn("model_name='gemma3:12b'", source)
                    self.assertIn("think=False", source)

    def test_generic_shopping_research_no_longer_loads_20b(self):
        for name in (
            "_extract_shopping_products_batch",
            "shopping_research_controller",
        ):
            source, _ = function_source(PROJECT_ROOT / "casper" / "browser.py", name)
            with self.subTest(function=name):
                self.assertNotIn("model_name='gpt-oss:20b'", source)
                self.assertIn("model_name='gemma3:12b'", source)

    def test_adapter_unloads_router_before_nonshopping_research(self):
        source, _ = function_source(
            PROJECT_ROOT / "casper" / "adapters.py", "execute_mode"
        )
        self.assertIn("unload_model('gemma3:12b')", source)
        for mode in ("NEWS_FEED", "FACT_LOOKUP", "CLAIM_CHECK", "SOCIAL_RESEARCH"):
            self.assertIn(repr(mode), source)

    def test_tools_mirrors_remain_identical(self):
        left = ast.dump(
            ast.parse((PROJECT_ROOT / "tools.py").read_text(encoding="utf-8")),
            include_attributes=False,
        )
        right = ast.dump(
            ast.parse((PROJECT_ROOT / "casper" / "tools.py").read_text(encoding="utf-8")),
            include_attributes=False,
        )
        self.assertEqual(left, right)


if __name__ == "__main__":
    unittest.main()
