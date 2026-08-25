import ast
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_contract_function():
    tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "recommendation_reply_contract"
    )
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"json": json}
    exec(compile(module, "main.py", "exec"), namespace)
    return namespace["recommendation_reply_contract"]


class RecommendationReplyContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = _load_contract_function()

    def test_preserves_exact_names_unknowns_and_shortfall(self):
        rendered = self.contract(
            {
                "plan": {"target_option_count": 3},
                "cards": [
                    {
                        "title": "Beijing Tasty House",
                        "requirements": [
                            {
                                "requirement": "Suitable for toddlers (2 years old)",
                                "status": "UNKNOWN",
                            },
                            {
                                "requirement": "Located in San Gabriel",
                                "status": "MATCH",
                            },
                        ],
                    },
                    {
                        "title": "Joy’s Express",
                        "requirements": [],
                    },
                ],
            }
        )
        self.assertIn('"verified_card_count": 2', rendered)
        self.assertIn('"requested_target_count": 3', rendered)
        self.assertIn('"title_verbatim": "Beijing Tasty House"', rendered)
        self.assertIn('"title_verbatim": "Joy’s Express"', rendered)
        self.assertIn("Suitable for toddlers (2 years old)", rendered)
        self.assertIn("Never translate", rendered)
        self.assertIn("UNKNOWN requirement is unverified", rendered)

    def test_final_prompt_appends_integrity_contract(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "get_ai_response"
        )
        rendered = ast.unparse(function)
        self.assertIn("recommendation_reply_contract", rendered)
        self.assertIn("name_placeholders", rendered)
        self.assertIn("recommendation_integrity_context", rendered)

    def test_evidence_prompts_forbid_candidate_name_translation(self):
        for relative_path in (
            "prompts/recommendation_extract.txt",
            "prompts/recommendation_guide_extract.txt",
        ):
            prompt = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("Never translate", prompt)
            self.assertIn("transliterate", prompt)


if __name__ == "__main__":
    unittest.main()
