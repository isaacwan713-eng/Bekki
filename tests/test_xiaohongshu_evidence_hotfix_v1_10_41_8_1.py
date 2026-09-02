from datetime import date
from io import BytesIO
import inspect
from pathlib import Path
import unittest

from PIL import Image, ImageFilter

import social_browser
import tools


ROOT = Path(__file__).resolve().parents[1]


def _scope(decision, entity, category, relation):
    return {
        "decision": decision,
        "entity_match": entity,
        "category_match": category,
        "relation_match": relation,
        "evidence": "可见标题或图片证据",
        "reason": "测试范围判定",
    }


class XiaohongshuEvidenceHotfixV1104181Tests(unittest.TestCase):
    def test_english_month_day_is_resolved_instead_of_replaced_by_today(self):
        self.assertEqual(
            tools._resolve_social_post_date("Feb 22", date(2026, 9, 1)),
            date(2026, 2, 22),
        )

    def test_opened_detail_date_overrides_search_inference_and_expires_post(self):
        items, details, warnings, dropped = tools.reconcile_social_detail_dates(
            [
                {
                    "title": "aespa辛拉面代言开箱",
                    "resolved_date": "2026-08-31",
                }
            ],
            [
                {
                    "platform": "xiaohongshu",
                    "post_title": "aespa辛拉面代言开箱",
                    "visible_time_text": "Feb 22",
                    "evidence_level": "opened_multimodal",
                }
            ],
            selection_mode="RECENT",
            recency_days=30,
            current_date="2026-09-01",
        )
        self.assertEqual(items, [])
        self.assertEqual(details, [])
        self.assertEqual(dropped, 1)
        self.assertTrue(any("2026-02-22" in value for value in warnings))

    def test_visible_four_days_ago_corrects_search_card_date(self):
        items, details, warnings, dropped = tools.reconcile_social_detail_dates(
            [{"title": "🇭🇰出 aespa 辛拉面小卡", "resolved_date": "2026-08-31"}],
            [
                {
                    "platform": "xiaohongshu",
                    "post_title": "🇭🇰出 aespa 辛拉面小卡",
                    "visible_time_text": "4天前",
                    "evidence_level": "search_only",
                }
            ],
            selection_mode="RECENT",
            recency_days=30,
            current_date="2026-09-01",
        )
        self.assertEqual(dropped, 0)
        self.assertEqual(items[0]["resolved_date"], "2026-08-28")
        self.assertEqual(items[0]["date_source"], "search_card_visible")
        self.assertEqual(details[0]["resolved_date"], "2026-08-28")
        self.assertTrue(any("覆盖搜索页推算日期" in value for value in warnings))

    def test_completely_unrelated_recommendations_are_hard_filtered(self):
        recent = [
            {"title": "aespa＆辛拉面联名", "relevance_score": 95},
            {"title": "777_", "relevance_score": 80},
            {"title": "背影一般…正脸绝了", "relevance_score": 60},
        ]
        details = [
            {"post_title": item["title"]} for item in recent
        ]
        introductions = [
            {
                "post_title": "aespa＆辛拉面联名",
                "scope_match": _scope("INCLUDE", "EXACT", "EXACT", "EXACT"),
            },
            {
                "post_title": "777_",
                "scope_match": _scope(
                    "EXCLUDE", "COMPATIBLE_VARIANT", "EXACT", "NONE"
                ),
            },
            {
                "post_title": "背影一般…正脸绝了",
                "scope_match": _scope("EXCLUDE", "NONE", "NONE", "NONE"),
            },
        ]
        kept, kept_details, kept_intros, removed = tools.filter_social_scope_matches(
            recent, details, introductions
        )
        self.assertEqual([item["title"] for item in kept], ["aespa＆辛拉面联名"])
        self.assertEqual(len(kept_details), 1)
        self.assertEqual(len(kept_intros), 1)
        self.assertEqual(set(removed), {"777_", "背影一般…正脸绝了"})

    def test_legacy_explicit_unrelated_text_cannot_build_a_card(self):
        recent = [{"title": "毛绒挂件", "relevance_score": 95}]
        detail = [{"post_title": "毛绒挂件", "platform": "xiaohongshu"}]
        intro = [{"post_title": "毛绒挂件", "answer_relevance": "与本次问题无关。"}]
        self.assertEqual(
            tools.build_social_cards(
                recent,
                detail,
                intro,
                {"observations": []},
                selection_mode="RELEVANCE",
                include_unranked=True,
            ),
            [],
        )

    def test_blurred_placeholder_is_rejected_but_sharp_media_is_kept(self):
        sharp = Image.new("RGB", (400, 300), "white")
        pixels = sharp.load()
        for y in range(300):
            for x in range(400):
                if ((x // 20) + (y // 20)) % 2:
                    pixels[x, y] = (15, 15, 15)

        def encode(image):
            output = BytesIO()
            image.save(output, "JPEG", quality=88)
            return output.getvalue()

        blurred = sharp.filter(ImageFilter.GaussianBlur(28))
        self.assertTrue(social_browser._detailed_raster_evidence(encode(sharp)))
        self.assertFalse(social_browser._detailed_raster_evidence(encode(blurred)))

    def test_xiaohongshu_video_uses_opened_player_frames(self):
        source = inspect.getsource(social_browser._capture_social_post_assets)
        self.assertIn("_capture_xiaohongshu_video_frames", source)
        self.assertIn('"kind": "video_frame"', source)
        prompt = (ROOT / "prompts" / "social_post_introduction.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("Xiaohongshu 视频帧", prompt)

    def test_search_preview_uses_media_raster_not_whole_card_crop(self):
        source = inspect.getsource(social_browser.resolve_social_post_targets)
        branch = source.split('if platform == "xiaohongshu":', 1)[1]
        self.assertIn("_download_post_image_jpeg", branch)
        self.assertIn("_detailed_raster_evidence", branch)

    def test_scope_schema_and_prompt_define_acceptable_deviation(self):
        item_schema = tools._SOCIAL_POST_DETAIL_SCHEMA["properties"]["items"][
            "items"
        ]
        self.assertIn("scope_match", item_schema["required"])
        prompt = (ROOT / "prompts" / "social_post_introduction.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("946 ml stainless insulated cup", prompt)
        self.assertIn("generic Winter photocard", prompt)
        self.assertIn("plush keychain", prompt)


if __name__ == "__main__":
    unittest.main()
