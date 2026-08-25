import ast
import json
from pathlib import Path
import re
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_final_parser_functions():
    tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
    wanted = {
        "_display_only_reply_from_broken_json",
        "parse_ai_result",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted
    ]
    namespace = {"json": json, "re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "main.py", "exec"), namespace)
    return namespace


class StableV11FinalJsonTests(unittest.TestCase):
    def test_unescaped_inner_quotes_recover_display_reply_only(self):
        functions = _load_final_parser_functions()
        broken = (
            '```json\n{"reply":"我今天很开心 translates to "I\'m very happy '
            'today."","highlights":[],"memory":null,"pending_action":null}\n```'
        )
        result, error = functions["parse_ai_result"](
            broken,
            allow_display_recovery=True,
        )
        self.assertIsNotNone(error)
        self.assertEqual(
            result["reply"],
            '我今天很开心 translates to "I\'m very happy today."',
        )
        self.assertEqual(result["highlights"], [])
        self.assertIsNone(result["memory"])
        self.assertIsNone(result["pending_action"])

    def test_final_generation_is_schema_bound_and_has_ai_recovery(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("response_format=FINAL_RESPONSE_SCHEMA", source)
        self.assertIn('"prompts/final_response_json_recover.txt"', source)
        self.assertIn("[AI JSON RECOVERED BY MODEL]", source)


class StableV11RoutingPromptTests(unittest.TestCase):
    def test_magi_examples_cover_observed_failures_without_zero_anchor(self):
        prompt = (PROJECT_ROOT / "prompts" / "magi_gate.txt").read_text(
            encoding="utf-8"
        )
        for text in (
            "曼联最近有什么新闻",
            "打开回收站",
            "查找名为 test.txt",
            "帮我翻译成英文",
            "1+1等于多少",
        ):
            self.assertIn(text, prompt)
        self.assertNotIn('"confidence":0.0', prompt)

    def test_melchior_prompt_is_compact_and_distinguishes_news_from_fact(self):
        prompt = (PROJECT_ROOT / "prompts" / "melchior_router.txt").read_text(
            encoding="utf-8"
        )
        self.assertLess(len(prompt.encode("utf-8")), 12000)
        self.assertIn('"曼联最近有什么新闻" -> NEWS_FEED', prompt)
        self.assertIn('"曼联下一场比赛是什么时候" -> FACT_LOOKUP', prompt)


if __name__ == "__main__":
    unittest.main()
