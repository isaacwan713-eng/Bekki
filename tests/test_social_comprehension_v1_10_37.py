import base64
from datetime import date
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import managed_browser
import social_browser
import tools


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _recent(title="帖子 A"):
    return {
        "title": title,
        "author": "作者 A",
        "resolved_date": "2026-08-31",
        "engagement": "18",
        "relevance_score": 90,
        "relevance_reason": "与问题直接相关。",
    }


def _detail(title="帖子 A"):
    return {
        "platform": "xiaohongshu",
        "post_title": title,
        "url": "https://www.rednote.com/explore/a",
        "search_visible_text": title + " 18",
        "visible_text": title + " Kin Khao Thai Eatery 人均$15左右",
        "visual_frame": "main-frame",
        "visual_frames": ["main-frame", "page-frame"],
        "image_url": "https://sns-img.example.com/a.jpg",
    }


def _understanding(title="帖子 A"):
    return {
        "post_title": title,
        "primary_subject": "Kin Khao Thai Eatery",
        "primary_subject_evidence": "Kin Khao Thai Eatery",
        "content_summary": "帖子介绍该餐厅，并写明人均约 15 美元。",
        "textual_findings": [
            {
                "finding": "正文写明人均约 15 美元。",
                "evidence_quote": "人均$15左右",
            }
        ],
        "image_summary": "主图展示桌面上的多道菜。",
        "visual_findings": [
            {
                "finding": "桌面摆放多道菜。",
                "visible_basis": "画面中可见多个餐盘",
                "confidence": "high",
            }
        ],
        "answer_relevance": "可用于了解菜品和价格，儿童设施未知。",
        "uncertainty": "未看到儿童菜单或游乐设施。",
    }


class SocialComprehensionV11037Tests(unittest.TestCase):
    def test_each_post_receives_two_title_bound_visual_frames(self):
        captured = []

        def model(_prompt, input_text, **kwargs):
            captured.append((json.loads(input_text), kwargs))
            return {"items": [_understanding()]}

        with patch.object(tools, "run_ai_prompt", side_effect=model):
            result = tools.extract_social_post_introductions(
                "去小红书找 Arcadia 亲子餐厅",
                [_recent()],
                [_detail()],
                {"observations": []},
            )

        self.assertEqual(len(captured), 1)
        packet, kwargs = captured[0]
        opened = packet["opened_post_details"][0]
        self.assertEqual(opened["visual_image_numbers"], [1, 2])
        self.assertEqual(kwargs["images"], ["main-frame", "page-frame"])
        self.assertEqual(result[0]["primary_subject"], "Kin Khao Thai Eatery")
        self.assertEqual(len(result[0]["textual_findings"]), 1)
        self.assertEqual(len(result[0]["visual_findings"]), 1)

    def test_failed_vision_json_retries_text_only_without_visual_claims(self):
        retry_output = _understanding()
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=(ValueError("malformed vision JSON"), {"items": [retry_output]}),
        ) as model:
            result = tools.extract_social_post_introductions(
                "查找餐厅",
                [_recent()],
                [_detail()],
                {"observations": []},
            )

        self.assertEqual(model.call_count, 2)
        self.assertNotIn("images", model.call_args.kwargs)
        self.assertEqual(result[0]["image_summary"], "")
        self.assertEqual(result[0]["visual_findings"], [])
        self.assertTrue(result[0]["content_summary"])

    def test_cross_post_synthesis_answers_and_exposes_location_conflict(self):
        summaries = tools.build_social_post_summaries(
            [_recent("Plaza Arkadia亲子cafe"), _recent("Arcadia泰国菜")],
            [
                {
                    "post_title": "Plaza Arkadia亲子cafe",
                    "content_summary": "帖子使用 RM 计价。",
                    "introduction": "帖子使用 RM 计价。",
                    "textual_findings": [
                        {"finding": "最低消费以 RM 计价。", "evidence_quote": "rm30"}
                    ],
                    "visual_findings": [],
                    "answer_relevance": "地点可能不是加州 Arcadia。",
                    "uncertainty": "地点存在同名冲突。",
                    "engagement": {},
                },
                {
                    "post_title": "Arcadia泰国菜",
                    "content_summary": "帖子写明人均$15。",
                    "introduction": "帖子写明人均$15。",
                    "textual_findings": [
                        {"finding": "人均约 15 美元。", "evidence_quote": "人均$15"}
                    ],
                    "visual_findings": [],
                    "answer_relevance": "儿童设施未知。",
                    "uncertainty": "不是专门亲子餐厅。",
                    "engagement": {},
                },
            ],
            selection_mode="RELEVANCE",
        )
        raw = {
            "answer": "目前不能把 Plaza Arkadia 当作加州 Arcadia 的亲子餐厅；RM 计价显示地点存在冲突。其余帖子也没有证明专门的儿童设施。",
            "findings": [
                {
                    "post_title": "Plaza Arkadia亲子cafe",
                    "finding": "最低消费以 RM 计价，地点需要排除或确认。",
                },
                {
                    "post_title": "Arcadia泰国菜",
                    "finding": "帖子只支持餐厅与人均价格，不支持亲子设施。",
                },
            ],
            "limitations": ["样本没有高脚椅、儿童菜单或游乐区的可靠证据。"],
            "confidence": "medium",
        }
        with patch.object(tools, "run_ai_prompt", return_value=raw):
            reply = tools.synthesize_social_research_reply(
                "去小红书搜索 Arcadia 亲子餐厅",
                "Arcadia 亲子餐厅",
                {"page_summary": "相关帖子"},
                summaries,
                ["xiaohongshu"],
                "RELEVANCE",
            )
        self.assertIn("不能把 Plaza Arkadia 当作加州 Arcadia", reply)
        self.assertIn("主要依据", reply)
        self.assertIn("需要注意", reply)

    def test_compact_reddit_relative_times_are_resolved(self):
        self.assertEqual(
            tools._resolve_social_post_date("4d ago", date(2026, 8, 31)),
            date(2026, 8, 27),
        )
        self.assertEqual(
            tools._resolve_social_post_date("12h ago", date(2026, 8, 31)),
            date(2026, 8, 31),
        )

    def test_reddit_community_scope_is_hard_bounded(self):
        communities = tools._requested_reddit_communities(
            "microduck review r/robotics"
        )
        self.assertTrue(
            tools._within_reddit_community_scope(
                {
                    "platform": "reddit",
                    "url": "https://www.reddit.com/r/robotics/comments/abc/post/",
                },
                communities,
            )
        )
        self.assertFalse(
            tools._within_reddit_community_scope(
                {
                    "platform": "reddit",
                    "url": "https://www.reddit.com/r/technology/comments/abc/post/",
                },
                communities,
            )
        )

    def test_background_window_uses_same_persistent_profile(self):
        sent = []

        class Session:
            def send(self, method, payload):
                sent.append((method, payload))
                if method == "Browser.getWindowForTarget":
                    return {"windowId": 7}
                return {}

            def detach(self):
                return None

        context = type(
            "Context", (), {"new_cdp_session": lambda self, page: Session()}
        )()
        managed_browser._background_announced = False
        self.assertTrue(managed_browser.keep_page_background(context, object()))
        self.assertIn(
            (
                "Browser.setWindowBounds",
                {"windowId": 7, "bounds": {"windowState": "minimized"}},
            ),
            sent,
        )
        source = inspect.getsource(social_browser)
        self.assertNotIn("bring_to_front()", source)
        manager_source = inspect.getsource(managed_browser.ensure_browser)
        self.assertIn("--user-data-dir=", manager_source)
        self.assertIn("--profile-directory=Default", manager_source)

    def test_new_prompt_does_not_delegate_engagement_guessing(self):
        prompt = (PROJECT_ROOT / "prompts" / "social_post_introduction.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("Do not output engagement", prompt)
        self.assertNotIn("engagement.likes", prompt)

    def test_root_and_casper_v37_mirrors_match(self):
        for relative in (
            "tools.py",
            "social_browser.py",
            "prompts/social_post_introduction.txt",
            "prompts/social_synthesis.txt",
        ):
            self.assertEqual(
                (PROJECT_ROOT / relative).read_bytes(),
                (PROJECT_ROOT / "casper" / relative).read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
