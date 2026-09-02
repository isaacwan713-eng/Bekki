from datetime import date
from unittest.mock import patch
from urllib.parse import urlparse
import unittest

import social_browser
import tools


class YouTubeRecencyChannelHotfixV110421Tests(unittest.TestCase):
    def test_exact_handle_shorts_query_uses_the_channel_shorts_tab(self):
        parsed = urlparse(
            social_browser.social_search_url("youtube", "@aespa Shorts")
        )
        self.assertEqual(parsed.netloc, "www.youtube.com")
        self.assertEqual(parsed.path, "/@aespa/shorts")
        self.assertEqual(parsed.query, "")
        self.assertTrue(
            social_browser._allowed_social_page_url(
                "youtube", "https://www.youtube.com/@aespa/shorts"
            )
        )

    def test_youtube_new_badge_is_deferred_until_opened_date_verification(self):
        model_evidence = {
            "page_summary": "YouTube Shorts results.",
            "recent_post_count": 1,
            "items": [{
                "title": "Whiplash dance challenge",
                "author": None,
                "time": "New",
                "engagement": "8.1K views",
                "relevance_score": 95,
                "relevance_reason": "Relevant Shorts result.",
                "kind": "other",
            }],
            "excluded_count": 0,
            "warnings": [],
        }
        with patch.object(tools, "run_ai_prompt", return_value=model_evidence):
            evidence = tools.extract_social_evidence(
                "Whiplash dance challenge New 8.1K views",
                recency_days=7,
                current_date=date(2026, 9, 2),
                selection_mode="RECENT",
                user_message="去油管找最近 7 天 @aespa 的 Shorts",
                query="@aespa Shorts",
                platforms=["youtube"],
            )
        self.assertEqual(len(evidence["items"]), 1)
        self.assertIsNone(evidence["items"][0]["resolved_date"])
        self.assertTrue(evidence["items"][0]["date_verification_required"])

        kept, kept_details, warnings, dropped = (
            tools.reconcile_social_detail_dates(
                evidence["items"],
                [{
                    "post_title": "Whiplash dance challenge",
                    "visible_time_text": "2026-09-01",
                    "evidence_level": "opened_multimodal",
                }],
                selection_mode="RECENT",
                recency_days=7,
                current_date=date(2026, 9, 2),
            )
        )
        self.assertEqual(dropped, 0)
        self.assertEqual(kept[0]["resolved_date"], "2026-09-01")
        self.assertFalse(kept[0]["date_verification_required"])
        self.assertEqual(len(kept_details), 1)
        self.assertFalse(warnings)

    def test_unopened_youtube_item_with_unknown_date_fails_closed(self):
        kept, kept_details, warnings, dropped = (
            tools.reconcile_social_detail_dates(
                [{
                    "title": "Undated Short",
                    "resolved_date": None,
                    "date_verification_required": True,
                }],
                [],
                selection_mode="RECENT",
                recency_days=7,
                current_date=date(2026, 9, 2),
            )
        )
        self.assertEqual(kept, [])
        self.assertEqual(kept_details, [])
        self.assertEqual(dropped, 1)
        self.assertTrue(any("无法验证" in value for value in warnings))

    def test_requested_handle_keeps_only_exact_opened_channel(self):
        recent = [
            {"title": "Official Short", "author": "aespa"},
            # A search model must not be allowed to make this official merely
            # because the title or query contains aespa.
            {"title": "Fan Short", "author": "aespa"},
        ]
        details = [
            {
                "post_title": "Official Short",
                "platform": "youtube",
                "youtube_channel_handle": "@aespa",
                "youtube_author": "aespa",
                "evidence_level": "opened_text",
            },
            {
                "post_title": "Fan Short",
                "platform": "youtube",
                "youtube_channel_handle": "@fan_edits",
                "youtube_author": "Fan Edits",
                "evidence_level": "opened_text",
            },
        ]
        kept, kept_details, warnings, dropped = (
            tools.filter_youtube_channel_scope(
                recent,
                details,
                tools._requested_youtube_handles(
                    "去油管找最近 7 天 @aespa 的 Shorts", "@aespa Shorts"
                ),
            )
        )
        self.assertEqual([item["title"] for item in kept], ["Official Short"])
        self.assertEqual(kept[0]["author"], "aespa")
        self.assertEqual(len(kept_details), 1)
        self.assertEqual(dropped, 1)
        self.assertTrue(any("@fan_edits" in value for value in warnings))

    def test_exact_channel_tab_is_safe_handle_fallback_after_video_open(self):
        kept, kept_details, warnings, dropped = (
            tools.filter_youtube_channel_scope(
                [{"title": "Official Short", "author": "invented"}],
                [{
                    "post_title": "Official Short",
                    "platform": "youtube",
                    "source_url": "https://www.youtube.com/@aespa/shorts",
                    "youtube_channel_handle": "",
                    "youtube_author": "",
                    "evidence_level": "opened_multimodal",
                }],
                ["@aespa"],
            )
        )
        self.assertEqual(dropped, 0)
        self.assertFalse(warnings)
        self.assertEqual(kept[0]["author"], "@aespa")
        self.assertEqual(kept[0]["author_source"], "youtube_channel_tab")
        self.assertEqual(len(kept_details), 1)

    def test_new_is_not_treated_as_a_relative_date(self):
        self.assertIsNone(
            tools._resolve_social_post_date("New", date(2026, 9, 2))
        )


if __name__ == "__main__":
    unittest.main()
