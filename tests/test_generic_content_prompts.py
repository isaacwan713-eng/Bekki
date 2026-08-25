import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERIC_PROMPTS = (
    "prompts/casper_content_research_plan.txt",
    "prompts/casper_content_research_plan_retry.txt",
    "prompts/casper_content_query_review.txt",
    "prompts/casper_content_query_review_retry.txt",
    "prompts/casper_content_query_compliance.txt",
    "prompts/casper_content_query_compliance_retry.txt",
)
LEARNING_PROMPTS = (
    "prompts/casper_content_learning_plan.txt",
    "prompts/casper_content_learning_plan_retry.txt",
    "prompts/casper_content_learning_grounding_review.txt",
    "prompts/casper_content_learning_grounding_review_retry.txt",
    "prompts/casper_content_learning_query.txt",
    "prompts/casper_content_learning_query_retry.txt",
    "prompts/casper_content_learning_query_review.txt",
    "prompts/casper_content_learning_query_review_retry.txt",
)
LEGACY_EXAMPLE_ANCHORS = (
    "fm26",
    "football manager",
    "manchester united",
    "曼联",
)


class GenericContentPromptTests(unittest.TestCase):
    def _read(self, relative_path):
        return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")

    def test_generic_prompts_make_current_request_authoritative(self):
        for relative_path in GENERIC_PROMPTS:
            with self.subTest(prompt=relative_path):
                text = self._read(relative_path)
                self.assertIn("CURRENT_REQUEST", text)
                self.assertIn("only authority", text)

    def test_generic_prompts_have_two_neutral_cross_app_examples(self):
        for relative_path in GENERIC_PROMPTS:
            with self.subTest(prompt=relative_path):
                text = self._read(relative_path)
                self.assertIn("Cities: Skylines II", text)
                self.assertIn("Minecraft Java Edition", text)

    def test_generic_prompts_do_not_embed_legacy_task_examples(self):
        for relative_path in GENERIC_PROMPTS:
            with self.subTest(prompt=relative_path):
                folded = self._read(relative_path).casefold()
                for anchor in LEGACY_EXAMPLE_ANCHORS:
                    self.assertNotIn(anchor, folded)

    def test_fit_context_identity_contract_survives_prompt_generalization(self):
        for relative_path in GENERIC_PROMPTS:
            with self.subTest(prompt=relative_path):
                text = self._read(relative_path)
                self.assertIn("fit_context_is_content_identity", text)
                self.assertIn("identity false", text.casefold())
                self.assertIn("identity true", text.casefold())

    def test_fm_install_selector_remains_a_bounded_adapter_prompt(self):
        text = self._read("prompts/casper_game_content_install.txt")
        self.assertIn("Football Manager tactic file", text)
        self.assertIn("exact opaque IDs", text)
        self.assertIn('"source_id"', text)
        self.assertIn('"destination_id"', text)

    def test_learning_prompts_are_current_turn_grounded_and_cross_app(self):
        combined = "\n".join(
            self._read(relative_path) for relative_path in LEARNING_PROMPTS
        )
        self.assertIn("Minecraft Java Edition", combined)
        self.assertIn("Cities: Skylines II", combined)
        for relative_path in LEARNING_PROMPTS:
            with self.subTest(prompt=relative_path):
                text = self._read(relative_path)
                self.assertIn("CURRENT_REQUEST", text)
                folded = text.casefold()
                for anchor in LEGACY_EXAMPLE_ANCHORS:
                    self.assertNotIn(anchor, folded)


if __name__ == "__main__":
    unittest.main()
