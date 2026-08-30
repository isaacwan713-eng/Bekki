import ast
import unittest
from pathlib import Path

from casper import browser


class RecommendationModelHandoffTests(unittest.TestCase):
    def test_controller_releases_large_and_compact_models_before_recommendation(self):
        source = Path(browser.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        controller = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "product_recommendation_controller"
        )
        rendered = ast.unparse(controller)
        self.assertIn("('gemma4:12b', 'llama3.2:latest')", rendered)
        self.assertIn("unload_model(model_name)", rendered)
        self.assertIn("unload_model('gemma4:12b')", rendered)
        self.assertNotIn("model_name='gpt-oss:20b'", rendered)
        self.assertIn("_ask_ai_for_recommendation_options", rendered)
        self.assertIn("_verify_ai_recommendation_options", rendered)

    def test_planner_uses_required_12b_ai_not_compact_llama(self):
        source = Path(browser.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        planner = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_build_ai_recommendation_plan"
        )
        rendered = ast.unparse(planner)
        self.assertIn("model_name='gemma4:12b'", rendered)
        self.assertNotIn("llama3.2:latest", rendered)
        self.assertNotIn("gpt-oss:20b", rendered)
        self.assertNotIn("json_schema=", rendered)


if __name__ == "__main__":
    unittest.main()
