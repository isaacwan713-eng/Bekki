import ast
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from casper import recommendation


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_main_name_functions():
    tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
    names = {
        "recommendation_name_placeholders",
        "recommendation_reply_contract",
        "_substitute_candidate_names",
    }
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"json": json}
    exec(compile(module, "main.py", "exec"), namespace)
    return namespace


class FixedComparisonIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.names = [
            "Beijing Tasty House",
            "小陸子清粥店",
            "小美快餐‧小吃‧冰果",
        ]
        self.plan = {
            "candidate_scope": "FIXED",
            "allowed_candidate_names": self.names,
            "target_option_count": 3,
            "requirements": ["Suitable for elderly", "Suitable for toddler"],
        }

    def test_unrelated_guide_cannot_create_fixed_candidate_evidence(self):
        page = {"content": "A list of thriller films and streaming picks."}
        ai_output = {
            "candidates": [
                {
                    "title": self.names[0],
                    "summary": "Invented from the plan rather than the page.",
                }
            ]
        }
        with patch.object(recommendation, "_ai", return_value=ai_output) as ai:
            result = recommendation._extract_guide_candidates(
                "compare the three",
                "RESTAURANT",
                self.plan,
                {"title": "Movie list", "url": "https://example.test"},
                page,
            )
        self.assertEqual(result, [])
        ai.assert_not_called()

    def test_guide_accepts_only_fixed_name_visibly_present_on_page(self):
        page = {
            "content": "A local dining guide that discusses 小陸子清粥店 only."
        }
        ai_output = {
            "candidates": [
                {"title": self.names[0], "summary": "Not on this page."},
                {
                    "title": self.names[1],
                    "summary": "The page discusses this restaurant.",
                    "requirements": [],
                    "sections": [],
                    "unknowns": [],
                },
            ]
        }
        with patch.object(recommendation, "_ai", return_value=ai_output):
            result = recommendation._extract_guide_candidates(
                "compare the three",
                "RESTAURANT",
                self.plan,
                {"title": "Dining guide", "url": "https://example.test"},
                page,
            )
        self.assertEqual([item["title"] for item in result], [self.names[1]])

    def test_visible_grounding_tolerates_display_punctuation_variants(self):
        page = {"content": "小美快餐 · 小吃 · 冰果 is listed on this page."}
        self.assertEqual(
            recommendation._visible_fixed_candidate_names(self.plan, page),
            [self.names[2]],
        )

    def test_fixed_selection_keeps_best_record_for_each_name(self):
        options = [
            {"title": self.names[0], "evidence_completeness": 20, "source_score": 90},
            {"title": self.names[0], "evidence_completeness": 70, "source_score": 60},
            {"title": self.names[1], "evidence_completeness": 10, "source_score": 50},
            {"title": self.names[2], "evidence_completeness": 5, "source_score": 40},
        ]
        selected = recommendation._select_distinct_candidates(
            "compare", "RESTAURANT", self.plan, options
        )
        self.assertEqual([item["title"] for item in selected], self.names)
        self.assertEqual(selected[0]["evidence_completeness"], 70)

    def test_missing_fixed_candidate_stays_in_comparison_as_unknown(self):
        complete = recommendation._complete_fixed_candidates(
            self.plan,
            "RESTAURANT",
            [{
                "title": self.names[0],
                "evidence_completeness": 60,
                "source_score": 70,
            }],
        )
        self.assertEqual([item["title"] for item in complete], self.names)
        self.assertEqual(
            complete[2]["evidence_scope"],
            "FIXED_CANDIDATE_PLACEHOLDER",
        )
        self.assertTrue(all(
            item["status"] == "UNKNOWN"
            for item in complete[2]["requirements"]
        ))

    def test_name_placeholders_cover_fixed_names_not_only_cards(self):
        namespace = _load_main_name_functions()
        placeholders = namespace["recommendation_name_placeholders"](
            {
                "recommendation_domain": "RESTAURANT",
                "plan": self.plan,
                "cards": [{"title": self.names[0]}],
            },
            "RECOMMENDATION_RESEARCH",
        )
        self.assertEqual(
            [item["title"] for item in placeholders],
            self.names,
        )

    def test_integrity_contract_keeps_all_fixed_names_with_fewer_cards(self):
        namespace = _load_main_name_functions()
        search_result = {
            "recommendation_domain": "RESTAURANT",
            "plan": self.plan,
            "cards": [{"title": self.names[0], "requirements": []}],
            "results": [
                {
                    "title": name,
                    "requirements": [{
                        "requirement": "Suitable for toddler",
                        "status": "UNKNOWN",
                    }],
                }
                for name in self.names
            ],
        }
        placeholders = namespace["recommendation_name_placeholders"](
            search_result,
            "RECOMMENDATION_RESEARCH",
        )
        rendered = namespace["recommendation_reply_contract"](
            search_result,
            placeholders,
        )
        self.assertIn('"verified_card_count": 1', rendered)
        self.assertIn('"fixed_candidate_count": 3', rendered)
        for index in range(1, 4):
            self.assertIn(f'[[BEKKI_RESTAURANT_{index}]]', rendered)


if __name__ == "__main__":
    unittest.main()
