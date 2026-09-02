from pathlib import Path
import unittest
from unittest.mock import patch

import tools
from casper import browser


ROOT = Path(__file__).resolve().parents[1]


class UnifiedResultBlocksV11041Tests(unittest.TestCase):
    def test_recommendation_overview_does_not_repeat_candidate_details(self):
        verified = [
            {
                "title": "Yeti Rambler 20 oz Tumbler with Straw Lid",
                "brand": "Yeti",
                "summary": "20 oz stainless tumbler with reviewed insulation.",
                "verification_checks": [
                    {
                        "requirement": "保冷至少 12 小时",
                        "status": "MATCH",
                        "evidence": "Reviewed cold-retention test exceeded 12 hours.",
                    }
                ],
                "verification_source_domains": ["review.example"],
            },
            {
                "title": "Iron Flask 20 oz Tumbler with Straw",
                "brand": "Iron Flask",
                "summary": "20 oz stainless tumbler with a straw.",
                "verification_checks": [],
                "verification_source_domains": ["guide.example"],
            },
        ]
        model_result = {
            "reply": (
                "1. Yeti Rambler 20 oz Tumbler with Straw Lid 很耐用。\n"
                "2. Iron Flask 20 oz Tumbler with Straw 也符合要求。"
            ),
            "items": [
                {
                    "title": "Yeti Rambler 20 oz Tumbler with Straw Lid",
                    "context": "容量、材质与保冷证据都符合本次需求。",
                    "pros": ["保冷测试超过 12 小时"],
                    "cons": ["没有实时库存证据"],
                },
                {
                    "title": "Iron Flask 20 oz Tumbler with Straw",
                    "context": "容量和吸管结构符合需求。",
                    "pros": ["20 oz 不锈钢杯体"],
                    "cons": [],
                },
            ],
        }
        plan = {"target_count": 2, "count_policy": "USER_EXPLICIT"}
        with patch.object(tools, "run_ai_prompt", return_value=model_result):
            reply = browser._build_ai_verified_recommendation_reply(
                "推荐两个杯子", plan, verified
            )

        self.assertNotIn("Yeti Rambler", reply)
        self.assertNotIn("Iron Flask", reply)
        self.assertIn("下方对应卡片", reply)
        self.assertEqual(
            verified[0]["card_summary"],
            "容量、材质与保冷证据都符合本次需求。",
        )
        self.assertEqual(
            verified[0]["presentation_sections"][0]["pros"],
            ["保冷测试超过 12 小时"],
        )

    def test_recommendation_prompt_requires_item_context_image_link_blocks(self):
        prompt = (
            ROOT / "prompts" / "casper_product_recommendation_final.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("Never list, number, name", prompt)
        self.assertIn('"context":"complete candidate-specific fit explanation"', prompt)
        self.assertIn("context, matching image, then matching source link", prompt)

    def test_social_findings_move_into_the_matching_card(self):
        summaries = [
            {
                "post_title": "帖子一",
                "description": "可验证的帖子内容。",
                "understanding_available": True,
                "evidence_level": "opened_text",
                "textual_findings": [],
                "visual_findings": [],
                "price_observations": [],
            }
        ]
        cards = [
            {
                "title": "展示名称",
                "metadata": {"post_title": "帖子一"},
                "sections": [],
            }
        ]
        model_result = {
            "answer": "这次样本显示一个明确的共同结论。",
            "findings": [
                {"post_title": "帖子一", "finding": "这条帖子的具体结论。"}
            ],
            "limitations": ["样本量有限。"],
            "confidence": "medium",
        }
        with patch.object(tools, "run_ai_prompt", return_value=model_result):
            reply = tools.synthesize_social_research_reply(
                "总结这些帖子",
                "测试",
                {},
                summaries,
                ["xiaohongshu"],
                "RELEVANCE",
                cards=cards,
            )

        self.assertNotIn("主要依据", reply)
        self.assertNotIn("这条帖子的具体结论", reply)
        self.assertEqual(cards[0]["sections"][0]["kind"], "fit")
        self.assertEqual(
            cards[0]["sections"][0]["text"], "这条帖子的具体结论。"
        )

    def test_social_fallback_keeps_per_post_text_out_of_overview(self):
        summaries = [
            {
                "post_title": "帖子一",
                "description": "不应在总览重复的逐帖说明。",
                "author": "作者",
            }
        ]
        reply = tools.render_social_research_reply(
            {"page_summary": "这是跨帖子总结。"},
            summaries,
            [{"title": "帖子一"}],
            platforms=["xiaohongshu"],
            selection_mode="RELEVANCE",
            bundle_card_context=True,
        )
        self.assertIn("这是跨帖子总结", reply)
        self.assertIn("对应说明、图片与原帖链接", reply)
        self.assertNotIn("不应在总览重复的逐帖说明", reply)

    def test_global_prompts_define_the_card_first_nonduplicate_contract(self):
        full = (ROOT / "prompts" / "system.txt").read_text(encoding="utf-8")
        light = (ROOT / "prompts" / "system_light.txt").read_text(
            encoding="utf-8"
        )
        synthesis = (ROOT / "prompts" / "social_synthesis.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("card-first presentation contract", full)
        self.assertIn("same content is not shown twice", " ".join(light.split()))
        self.assertIn("not a title-by-title list", synthesis)

    def test_root_and_casper_runtime_mirrors_match(self):
        self.assertEqual(
            (ROOT / "tools.py").read_bytes(),
            (ROOT / "casper" / "tools.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "result_cards.py").read_bytes(),
            (ROOT / "casper" / "result_cards.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "prompts" / "social_synthesis.txt").read_bytes(),
            (ROOT / "casper" / "prompts" / "social_synthesis.txt").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
