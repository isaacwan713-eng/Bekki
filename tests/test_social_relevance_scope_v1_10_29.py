from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import unittest
from unittest.mock import patch

import social_browser
import tools


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _item(title, engagement, relevance_score, when=None):
    return {
        "title": title,
        "author": "作者",
        "time": when,
        "engagement": engagement,
        "relevance_score": relevance_score,
        "relevance_reason": "可见文字与完整问题的匹配程度。",
        "kind": "discussion",
    }


class SocialRelevanceScopeV11029Tests(unittest.TestCase):
    def test_existing_query_ai_owns_time_scope_without_new_gate(self):
        no_time = {
            "query": "又一充电中 袁雨桢",
            "selection_mode": "RELEVANCE",
            "recency_days": None,
        }
        with patch.object(tools, "run_ai_prompt", return_value=no_time) as model:
            plan = tools.build_social_query_plan(
                "去B站搜索 又一充电中 袁雨桢",
                ["bilibili"],
            )
        self.assertEqual(plan, no_time)
        self.assertEqual(model.call_count, 1)

        recent = {
            "query": "又一充电中",
            "selection_mode": "RECENT",
            "recency_days": 7,
        }
        with patch.object(tools, "run_ai_prompt", return_value=recent):
            plan = tools.build_social_query_plan(
                "去B站搜索最近一周 又一充电中",
                ["bilibili"],
            )
        self.assertEqual(plan, recent)

        prompt = (
            PROJECT_ROOT / "prompts" / "social_query.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("No explicit time constraint means", prompt)
        self.assertIn("又一充电中 袁雨桢", prompt)
        self.assertIn('"selection_mode":"RELEVANCE"', prompt)

    def test_relevance_mode_keeps_old_and_undated_exact_matches(self):
        raw = {
            "page_summary": "与两者关联有关的讨论。",
            "recent_post_count": 3,
            "items": [
                _item("热门但只谈又一", "6075", 30, "今天"),
                _item("又一充电中与袁雨桢的关联讨论", "2", 98, "2022-05-01"),
                _item("无日期的双方线索整理", None, 82, None),
            ],
            "excluded_count": 0,
            "warnings": [],
        }
        with patch.object(tools, "run_ai_prompt", return_value=raw):
            evidence = tools.extract_social_evidence(
                "visible page",
                recency_days=None,
                current_date=date(2026, 8, 30),
                selection_mode="RELEVANCE",
                user_message="去B站搜索 又一充电中 袁雨桢",
                query="又一充电中 袁雨桢",
            )
        self.assertEqual(evidence["selection_mode"], "RELEVANCE")
        self.assertIsNone(evidence["recency_days"])
        self.assertEqual(evidence["selected_post_count"], 3)
        self.assertEqual(
            [item["title"] for item in evidence["items"]],
            [
                "又一充电中与袁雨桢的关联讨论",
                "无日期的双方线索整理",
                "热门但只谈又一",
            ],
        )
        self.assertIsNone(evidence["items"][1]["resolved_date"])

    def test_recent_mode_still_enforces_explicit_window(self):
        raw = {
            "page_summary": "近期讨论。",
            "recent_post_count": 3,
            "items": [
                _item("今天的帖子", "3", 70, "今天"),
                _item("旧帖子", "99", 99, "2025-01-01"),
                _item("无日期帖子", "100", 100, None),
            ],
            "excluded_count": 0,
            "warnings": [],
        }
        with patch.object(tools, "run_ai_prompt", return_value=raw):
            evidence = tools.extract_social_evidence(
                "visible page",
                recency_days=7,
                current_date=date(2026, 8, 30),
                selection_mode="RECENT",
            )
        self.assertEqual(evidence["selection_mode"], "RECENT")
        self.assertEqual(evidence["recency_days"], 7)
        self.assertEqual(
            [item["title"] for item in evidence["items"]],
            ["今天的帖子"],
        )
        self.assertEqual(evidence["excluded_count"], 2)

    def test_relevance_orders_summaries_and_cards_before_engagement(self):
        recent = [
            {
                **_item("热门邻近帖", "6075", 25, "今天"),
                "resolved_date": "2026-08-30",
            },
            {
                **_item("双方关系帖", "1", 97, None),
                "resolved_date": None,
            },
        ]
        summaries = tools.build_social_post_summaries(
            recent,
            [],
            selection_mode="RELEVANCE",
        )
        self.assertEqual(
            [item["post_title"] for item in summaries],
            ["双方关系帖", "热门邻近帖"],
        )

        details = [
            {
                "platform": "bilibili",
                "post_title": "热门邻近帖",
                "url": "https://www.bilibili.com/video/BV1popular",
                "image_url": "",
            },
            {
                "platform": "bilibili",
                "post_title": "双方关系帖",
                "url": "https://www.bilibili.com/video/BV1exact",
                "image_url": "",
            },
        ]
        cards = tools.build_social_cards(
            recent,
            details,
            [],
            {"observations": []},
            selection_mode="RELEVANCE",
        )
        self.assertEqual(
            [card["title"] for card in cards],
            ["双方关系帖", "热门邻近帖"],
        )

    def test_relevance_reply_uses_actual_platform_and_no_fake_window(self):
        summaries = [
            {
                "post_title": "双方关系帖",
                "description": "可见文字同时提到两个对象。",
                "author": "作者",
                "published_at": None,
                "likes": None,
                "comments": None,
                "shares": None,
                "search_visible_interaction": "2",
                "relevance_score": 97,
                "relevance_reason": "同时提到两个对象。",
            }
        ]
        reply = tools.render_social_research_reply(
            {
                "page_summary": "相关讨论围绕两者之间的关联。",
                "selection_mode": "RELEVANCE",
                "platforms": ["bilibili"],
            },
            summaries,
            [{"title": "双方关系帖"}],
            recency_days=None,
            platforms=["bilibili"],
            selection_mode="RELEVANCE",
        )
        self.assertIn("哔哩哔哩 (Bilibili)", reply)
        self.assertIn("按与问题的语义关联度排列", reply)
        self.assertIn("关联度最高的 1 条", reply)
        self.assertNotIn("小红书", reply)
        self.assertNotIn("最近 7 天", reply)
        self.assertNotIn("互动从多到少", reply)

    def test_platform_search_sort_follows_ai_scope(self):
        bili_relevance = parse_qs(urlparse(
            social_browser.social_search_url(
                "bilibili", "又一充电中 袁雨桢", "RELEVANCE"
            )
        ).query)
        bili_recent = parse_qs(urlparse(
            social_browser.social_search_url(
                "bilibili", "又一充电中", "RECENT"
            )
        ).query)
        reddit_relevance = parse_qs(urlparse(
            social_browser.social_search_url(
                "reddit", "microduck", "RELEVANCE"
            )
        ).query)
        reddit_recent = parse_qs(urlparse(
            social_browser.social_search_url(
                "reddit", "microduck", "RECENT"
            )
        ).query)
        self.assertEqual(bili_relevance["order"], ["totalrank"])
        self.assertEqual(bili_recent["order"], ["pubdate"])
        self.assertEqual(reddit_relevance["sort"], ["relevance"])
        self.assertEqual(reddit_recent["sort"], ["new"])

    def test_controller_does_not_apply_seven_days_without_user_request(self):
        plan = {
            "query": "又一充电中 袁雨桢",
            "selection_mode": "RELEVANCE",
            "recency_days": None,
        }
        evidence = {
            "page_summary": "",
            "recent_post_count": 0,
            "selected_post_count": 0,
            "items": [],
            "excluded_count": 0,
            "selection_mode": "RELEVANCE",
            "recency_days": None,
            "warnings": [],
        }
        with patch.object(
            tools, "build_social_query_plan", return_value=plan
        ), patch.object(
            tools.time, "sleep", return_value=None
        ), patch.object(
            tools.social_browser,
            "open_social_search",
            return_value={"url": "https://search.bilibili.com/all?keyword=x"},
        ) as opened, patch.object(
            tools.social_browser,
            "inspect_active_social_page",
            return_value={
                "url": "https://search.bilibili.com/all?keyword=x",
                "visible_text": "可见结果",
                "visual_frames": [],
                "post_candidates": [],
            },
        ), patch.object(
            tools, "extract_social_evidence", return_value=evidence
        ) as extracted, patch.object(
            tools,
            "extract_social_visual_evidence",
            return_value={
                "frames_analyzed": 0,
                "visual_summary": "",
                "observations": [],
                "warnings": [],
            },
        ), patch.object(
            tools.social_browser, "resolve_social_post_targets", return_value=[]
        ), patch.object(
            tools.social_browser, "inspect_social_post_details", return_value=[]
        ), patch.object(
            tools.social_browser, "close_social_browser"
        ), patch.object(
            tools, "extract_social_post_introductions", return_value=[]
        ):
            result = tools.social_research_controller(
                "去B站搜索 又一充电中 袁雨桢",
                ["bilibili"],
            )
        opened.assert_called_once_with(
            "bilibili",
            "又一充电中 袁雨桢",
            selection_mode="RELEVANCE",
        )
        self.assertEqual(
            extracted.call_args.kwargs["selection_mode"], "RELEVANCE"
        )
        self.assertIsNone(extracted.call_args.kwargs["recency_days"])
        self.assertEqual(result["selection_mode"], "RELEVANCE")
        self.assertIsNone(result["recency_days"])
        self.assertNotIn("last 7 days", result["context"])

    def test_root_and_casper_social_scope_copies_match(self):
        pairs = (
            ("tools.py", "casper/tools.py"),
            ("social_browser.py", "casper/social_browser.py"),
            ("prompts/social_query.txt", "casper/prompts/social_query.txt"),
            ("prompts/social_extract.txt", "casper/prompts/social_extract.txt"),
        )
        for left, right in pairs:
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    (PROJECT_ROOT / left).read_bytes(),
                    (PROJECT_ROOT / right).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
