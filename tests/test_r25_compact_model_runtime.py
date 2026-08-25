import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CompactModelRuntimeTests(unittest.TestCase):
    def test_runtime_python_never_references_20b(self):
        # Only the canonical runtime is executable. Backups, virtual
        # environments, build output, and update-package extracts may live
        # below the project directory but must not be mistaken for runtime.
        runtime_files = list(PROJECT_ROOT.glob("*.py"))
        casper_root = PROJECT_ROOT / "casper"
        if casper_root.is_dir():
            runtime_files.extend(casper_root.rglob("*.py"))
        offenders = []
        for path in runtime_files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if any(
                isinstance(node, ast.Constant)
                and node.value == "gpt-oss:20b"
                for node in ast.walk(tree)
            ):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
        self.assertEqual(offenders, [])

    def test_default_model_is_12b_in_both_tools_mirrors(self):
        for relative in ("tools.py", "casper/tools.py"):
            source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
            self.assertIn('MODEL_NAME = "gemma3:12b"', source)

    def test_tools_mirrors_are_ast_identical(self):
        left = ast.dump(
            ast.parse((PROJECT_ROOT / "tools.py").read_text(encoding="utf-8")),
            include_attributes=False,
        )
        right = ast.dump(
            ast.parse((PROJECT_ROOT / "casper/tools.py").read_text(encoding="utf-8")),
            include_attributes=False,
        )
        self.assertEqual(left, right)

    def test_model_manifest_requires_chat_router_and_bounded_ui_vision_models(self):
        manifest = json.loads(
            (PROJECT_ROOT / "MODEL_REQUIREMENTS.json").read_text(encoding="utf-8")
        )
        tags = {item["tag"] for item in manifest["models"] if item["required"]}
        self.assertEqual(
            tags,
            {"gemma3:12b", "gemma3:4b", "llama3.2:latest"},
        )

    def test_call_model_disables_unsupported_thinking_for_gemma(self):
        runtime_source = (PROJECT_ROOT / "model_runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('startswith(("gemma3:", "llama3.2:"))', runtime_source)
        self.assertIn("think = False", runtime_source)
        tools_source = (PROJECT_ROOT / "tools.py").read_text(encoding="utf-8")
        self.assertIn("return model_runtime.generate(", tools_source)
        self.assertIn("images=images", tools_source)

    def test_call_model_keeps_small_model_thinking_disabled(self):
        source = (PROJECT_ROOT / "model_runtime.py").read_text(encoding="utf-8")
        self.assertIn('startswith(("gemma3:", "llama3.2:"))', source)

    def test_final_persona_prompts_are_split_from_compact_core(self):
        core = (PROJECT_ROOT / "prompts/system_light.txt").read_text(
            encoding="utf-8"
        )
        light = (PROJECT_ROOT / "prompts/bekki_persona_light.txt").read_text(
            encoding="utf-8"
        )
        full = (PROJECT_ROOT / "prompts/bekki_persona_full.txt").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("32-year-old", core)
        self.assertIn("18-year-old virtual idol", light)
        self.assertIn("32-year-old former idol", light)
        self.assertIn("Balthasar", full)
        self.assertIn("serious", light.lower())
        self.assertIn("serious", full.lower())

    def test_main_applies_persona_only_at_final_writing_layer(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertNotIn('resource_path("prompts/system.txt")', source)
        self.assertIn("[FINAL PERSONA]", source)
        self.assertIn('interaction_mode == "COMPANION"', source)
        self.assertIn("persona_prompt = bekki_persona_full", source)
        self.assertIn("persona_prompt = bekki_persona_light", source)
        self.assertIn("system_prompt_light,", source)

    def test_all_research_modes_forward_results_to_the_ui_source_layer(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        for mode in (
            "FACT_LOOKUP",
            "CLAIM_CHECK",
            "NEWS_FEED",
            "SOCIAL_RESEARCH",
            "SHOPPING_RESEARCH",
            "RECOMMENDATION_RESEARCH",
        ):
            self.assertIn('"' + mode + '"', source)
        self.assertIn('item.get(\n                        "content_type",\n                        "SOURCE",', source)

    def test_existing_fact_and_product_final_calls_reuse_light_persona(self):
        browser = (PROJECT_ROOT / "casper/browser.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def _load_bekki_light_persona", browser)
        self.assertEqual(browser.count("_load_bekki_light_persona()"), 3)
        self.assertIn('evidence["bekki_final_persona"]', browser)
        self.assertIn('packet["bekki_final_persona"]', browser)
        for relative in (
            "prompts/casper_product_recommendation_final.txt",
            "prompts/casper_search_summary_audit.txt",
        ):
            prompt = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("bekki_final_persona", prompt)

if __name__ == "__main__":
    unittest.main()
