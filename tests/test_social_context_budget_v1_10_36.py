import json
import unittest
from unittest.mock import patch

import tools


def _recent(index):
    return {
        "title": f"帖子 {index}",
        "author": f"作者 {index}",
        "resolved_date": "2026-08-31",
        "engagement": str(index * 100),
        "relevance_score": 90 - index,
        "relevance_reason": f"帖子 {index} 与用户问题直接相关。",
    }


def _detail(index):
    return {
        "platform": "bilibili",
        "post_title": f"帖子 {index}",
        "url": f"https://www.bilibili.com/video/BV1budget{index}",
        "image_url": f"https://i0.hdslb.com/bfs/archive/{index}.jpg",
        "search_visible_text": "搜索卡片文字 " * 1000,
        "visible_text": "详情页正文 " * 5000,
        "visual_frame": f"frame-{index}",
    }


class SocialContextBudgetV11036Tests(unittest.TestCase):
    def test_three_long_details_are_strictly_compacted_inside_8k_context(self):
        captured = []

        def model(_prompt_path, input_text, **kwargs):
            captured.append(
                {
                    "packet": json.loads(input_text),
                    "input_text": input_text,
                    "kwargs": kwargs,
                }
            )
            return {"items": []}

        with patch.object(tools, "run_ai_prompt", side_effect=model):
            tools.extract_social_post_introductions(
                "请查找这些 Bilibili 内容" * 200,
                [_recent(index) for index in range(1, 4)],
                [_detail(index) for index in range(1, 4)],
                {"observations": []},
            )

        self.assertEqual(len(captured), 3)
        for call in captured:
            packet = call["packet"]
            self.assertLessEqual(
                len(packet["user_request"]),
                tools.SOCIAL_INTRO_USER_REQUEST_CHARS,
            )
            self.assertLessEqual(
                len(packet["opened_post_details"]),
                tools.SOCIAL_INTRO_BATCH_SIZE,
            )
            for detail in packet["opened_post_details"]:
                self.assertLessEqual(
                    len(detail["search_visible_text"]),
                    tools.SOCIAL_INTRO_SEARCH_TEXT_CHARS,
                )
                self.assertLessEqual(
                    len(detail["visible_text"]),
                    tools.SOCIAL_INTRO_DETAIL_TEXT_CHARS,
                )
            self.assertLess(len(call["input_text"]), 5500)
            self.assertEqual(call["kwargs"]["num_ctx"], 8192)
            self.assertEqual(call["kwargs"]["num_predict"], 1200)

    def test_optional_introduction_batch_failure_does_not_escape(self):
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=RuntimeError("request exceeds available context size"),
        ) as model:
            result = tools.extract_social_post_introductions(
                "查找帖子",
                [_recent(index) for index in range(1, 5)],
                [_detail(index) for index in range(1, 5)],
                {"observations": []},
            )

        self.assertEqual(result, [])
        self.assertEqual(model.call_count, 8)

    def test_evidence_only_summary_and_card_remain_useful(self):
        recent = _recent(1)
        detail = _detail(1)

        summaries = tools.build_social_post_summaries([recent], [])
        cards = tools.build_social_cards(
            [recent], [detail], [], {"observations": []},
            selection_mode="RELEVANCE",
        )

        self.assertEqual(len(summaries), 1)
        self.assertIn("与用户问题直接相关", summaries[0]["description"])
        self.assertEqual(len(cards), 1)
        self.assertIn("与用户问题直接相关", cards[0]["summary"])
        self.assertEqual(cards[0]["url"], detail["url"])

    def test_controller_keeps_reply_and_cards_after_unexpected_intro_failure(self):
        recent = _recent(1)
        candidate = {
            "platform": "bilibili",
            "url": _detail(1)["url"],
            "visible_text": "帖子 1 作者 1 互动 100",
            "image_url": _detail(1)["image_url"],
        }
        detail = {
            **candidate,
            "post_title": "帖子 1",
            "search_visible_text": candidate["visible_text"],
            "visual_frame": "",
        }
        with patch.object(
            tools,
            "build_social_query_plan",
            return_value={
                "query": "帖子 1",
                "selection_mode": "RELEVANCE",
                "recency_days": None,
            },
        ), patch.object(tools.time, "sleep", return_value=None), patch.object(
            tools.social_browser,
            "open_social_search",
            return_value={"url": "https://search.bilibili.com/all?keyword=x"},
        ), patch.object(
            tools.social_browser,
            "inspect_active_social_page",
            return_value={
                "url": "https://search.bilibili.com/all?keyword=x",
                "visible_text": candidate["visible_text"],
                "visual_frames": [],
                "post_candidates": [candidate],
            },
        ), patch.object(
            tools.social_browser,
            "resolve_social_post_targets",
            return_value=[],
        ), patch.object(
            tools.social_browser,
            "inspect_social_post_details",
            return_value=[detail],
        ), patch.object(
            tools.social_browser, "close_social_browser"
        ), patch.object(
            tools,
            "extract_social_evidence",
            return_value={
                "page_summary": "找到相关视频。",
                "items": [recent],
                "warnings": [],
            },
        ), patch.object(
            tools,
            "extract_social_visual_evidence",
            return_value={"observations": [], "warnings": []},
        ), patch.object(
            tools,
            "extract_social_post_introductions",
            side_effect=RuntimeError("unexpected introduction failure"),
        ):
            result = tools.social_research_controller(
                "去 Bilibili 查找帖子 1", ["bilibili"]
            )

        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(result["cards"]), 1)
        self.assertNotIn("帖子 1", result["direct_reply"])
        self.assertEqual(result["cards"][0]["title"], "帖子 1")
        self.assertIn("与用户问题直接相关", result["cards"][0]["summary"])


if __name__ == "__main__":
    unittest.main()
