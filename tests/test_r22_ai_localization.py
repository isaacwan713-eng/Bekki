import ast
from pathlib import Path
import unittest

from casper import browser


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AILocalizationTests(unittest.TestCase):
    def test_ai_owns_market_language_and_python_has_no_translation_mapping(self):
        prompt = (
            PROJECT_ROOT / "prompts" / "casper_product_recommendation_plan.txt"
        ).read_text(encoding="utf-8")
        browser_source = Path(browser.__file__).read_text(encoding="utf-8")
        self.assertIn("You, not Python, own market-language localization", prompt)
        self.assertIn("tumbler with straw", prompt)
        self.assertNotIn("吸管杯", browser_source)

    def test_exact_rejected_title_cannot_reenter_recovery(self):
        sources = [
            {
                "index": 1,
                "domain": "review.example",
                "title": "New review",
                "description": "New evidence",
                "url": "https://review.example/new",
            }
        ]
        raw = {
            "items": [
                {
                    "title": "Old Toddler Cup",
                    "brand": "Old",
                    "summary": "Repeated candidate.",
                    "source_indexes": [1],
                    "verification_queries": ["Old Toddler Cup category"],
                },
                {
                    "title": "Adult Straw Tumbler",
                    "brand": "New",
                    "summary": "New candidate.",
                    "source_indexes": [1],
                    "verification_queries": ["Adult Straw Tumbler category"],
                },
            ],
            "reply": "Two candidates.",
        }
        options, _reply = browser._accept_ai_recommendation_options(
            raw,
            sources,
            excluded_titles=["Old Toddler Cup"],
        )
        self.assertEqual(
            [item["title"] for item in options],
            ["Adult Straw Tumbler"],
        )

    def test_recovery_candidate_packet_uses_only_new_sources(self):
        tree = ast.parse(Path(browser.__file__).read_text(encoding="utf-8"))
        controller = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "product_recommendation_controller"
        )
        rendered = ast.unparse(controller)
        self.assertIn("recovery_packet['sources'] = recovery_sources", rendered)
        self.assertNotIn("recovery_packet['sources'] = sources", rendered)

    def test_recovery_ai_cannot_invent_features(self):
        prompt = (
            PROJECT_ROOT / "prompts" / "casper_product_recommendation_recovery.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("Do not add a material", prompt)
        self.assertIn("explicit `criteria`", prompt)


if __name__ == "__main__":
    unittest.main()
