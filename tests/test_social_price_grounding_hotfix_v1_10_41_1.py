import json
from pathlib import Path
import unittest
from unittest.mock import patch

import social_browser
import tools


ROOT = Path(__file__).resolve().parents[1]


class _AtomicClickPage:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def evaluate(self, script, title):
        self.calls.append((script, title))
        return self.result


class SocialPriceGroundingHotfixV110411Tests(unittest.TestCase):
    def test_search_engagement_next_to_repeated_title_is_not_price(self):
        source = "出Karina小卡！ 柚子汽水 1天前 8\n出Karina小卡！"
        raw = tools._price_observations_from_text(source)
        self.assertEqual(raw[0]["normalized_amount"], 8)

        cleaned = tools._clean_social_price_observations(
            [], source, True, excluded_metric_values=("8",)
        )
        self.assertEqual(cleaned, [])

    def test_marketplace_price_shorthand_survives_without_currency(self):
        cleaned = tools._clean_social_price_observations(
            [], "330💼出柚小卡盘；卡价 250", False
        )
        self.assertEqual(
            [item["normalized_amount"] for item in cleaned], [330, 250]
        )
        self.assertTrue(all(item["currency_unknown"] for item in cleaned))

    def test_price_word_in_title_does_not_relabel_engagement(self):
        source = "24年的柳智敏卡价 Vicktob 7小时前 304"
        model_items = [
            {
                "raw_amount": "304",
                "normalized_amount": 304,
                "currency": None,
                "price_type": "displayed",
                "item_binding": None,
                "evidence_basis": "卡价 304",
                "confidence": "high",
            }
        ]
        self.assertEqual(
            tools._clean_social_price_observations(
                model_items,
                source,
                True,
                excluded_metric_values=("304",),
            ),
            [],
        )

    def test_exact_grounded_price_marker_can_survive_metric_collision(self):
        source = "卡价 304；搜索页可见互动 304"
        cleaned = tools._clean_social_price_observations(
            [], source, False, excluded_metric_values=("304",)
        )
        self.assertEqual(cleaned[0]["normalized_amount"], 304)

    def test_price_cards_require_grounded_price_not_engagement(self):
        recent = [
            {
                "title": "出Karina小卡！",
                "author": "柚子汽水",
                "engagement": "8",
                "relevance_score": 95,
            }
        ]
        details = [
            {
                "platform": "xiaohongshu",
                "post_title": "出Karina小卡！",
                "post_url": "https://www.rednote.com/explore/abc",
                "evidence_level": "opened_multimodal",
            }
        ]
        intros = [
            {
                "post_title": "出Karina小卡！",
                "introduction": "出售 Karina 小卡。",
                "price_observations": [],
            }
        ]
        with patch.object(
            tools.result_cards, "clean_cards", side_effect=lambda cards: cards
        ):
            cards = tools.build_social_cards(
                recent,
                details,
                intros,
                {"observations": []},
                selection_mode="RECENT",
                ranking_mode="PRICE",
                include_unranked=False,
            )
        self.assertEqual(cards, [])

    def test_price_synthesis_never_calls_model_or_promotes_engagement(self):
        summaries = [
            {
                "post_title": "出Karina小卡！",
                "search_visible_interaction": "8",
                "understanding_available": False,
                "price_observations": [],
            }
        ]
        with patch.object(
            tools, "run_ai_prompt", side_effect=AssertionError("model called")
        ):
            reply = tools.synthesize_social_research_reply(
                "查 Karina 小卡卡价",
                "aespa Karina 小卡卡价",
                {},
                summaries,
                ["xiaohongshu"],
                "RECENT",
                ranking_mode="PRICE",
                cards=[],
            )
        self.assertIn("互动数不会被当作价格", reply)
        self.assertNotIn("价格记录", reply)
        self.assertNotIn("数值为 8", reply)

    def test_price_synthesis_leaves_item_values_to_matching_cards(self):
        summaries = [
            {
                "post_title": "卡价盘",
                "understanding_available": True,
                "price_observations": [
                    {
                        "raw_amount": "250",
                        "normalized_amount": 250,
                        "currency": None,
                        "currency_unknown": True,
                        "price_type": "displayed",
                        "item_binding": "图一",
                        "evidence_basis": "图一 250",
                    }
                ],
            }
        ]
        with patch.object(
            tools, "run_ai_prompt", side_effect=AssertionError("model called")
        ):
            reply = tools.synthesize_social_research_reply(
                "查小卡价格",
                "小卡价格",
                {},
                summaries,
                ["xiaohongshu"],
                "RECENT",
                ranking_mode="PRICE",
                cards=[{"metadata": {"post_title": "卡价盘"}}],
            )
        self.assertIn("1 个价格数字", reply)
        self.assertIn("各自卡片", reply)
        self.assertNotIn("250", reply)
        self.assertNotIn("卡价盘", reply)

    def test_karina_request_activates_verified_chinese_aliases(self):
        captured = {}

        def model(_prompt, packet, **_kwargs):
            captured["packet"] = packet
            return {
                "page_summary": "卡价讨论",
                "recent_post_count": 1,
                "items": [
                    {
                        "title": "24年的柳智敏卡价",
                        "author": "Vicktob",
                        "time": "7小时前",
                        "engagement": "304",
                        "relevance_score": 40,
                        "relevance_reason": "不是 Karina",
                        "kind": "discussion",
                    }
                ],
                "excluded_count": 0,
                "warnings": [],
            }

        with patch.object(tools, "run_ai_prompt", side_effect=model):
            evidence = tools.extract_social_evidence(
                "24年的柳智敏卡价 Vicktob 7小时前 304",
                recency_days=30,
                current_date="2026-09-01",
                selection_mode="RECENT",
                user_message="查最近一个月 aespa Karina 小卡卡价",
                query="aespa Karina 小卡卡价",
                ranking_mode="PRICE",
            )
        item = evidence["items"][0]
        self.assertGreaterEqual(item["relevance_score"], 90)
        self.assertIn("已验证别名", item["relevance_reason"])
        self.assertIn("柳智敏", captured["packet"])
        self.assertIn("柚卡", captured["packet"])

    def test_atomic_fresh_title_click_uses_current_dom_node(self):
        page = _AtomicClickPage()
        self.assertTrue(
            social_browser._click_fresh_social_title_node(
                page, "aespa小卡市场价汇总"
            )
        )
        self.assertEqual(page.calls[0][1], "aespa小卡市场价汇总")

    def test_alias_prompt_contract_and_runtime_mirrors(self):
        extraction_prompt = (
            ROOT / "prompts" / "social_extract.txt"
        ).read_text(encoding="utf-8")
        introduction_prompt = (
            ROOT / "prompts" / "social_post_introduction.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("verified entity-alias", extraction_prompt.lower())
        self.assertIn("verified_entity_aliases", introduction_prompt.lower())
        for relative in (
            "tools.py",
            "social_browser.py",
            "prompts/social_extract.txt",
            "prompts/social_post_introduction.txt",
        ):
            self.assertEqual(
                (ROOT / relative).read_bytes(),
                (ROOT / "casper" / relative).read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
