import ast
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import tools
from casper import browser


class GPTJSONCompatibilityTests(unittest.TestCase):
    REGION = {
        "country_code": "US",
        "country_name": "United States",
        "preferred_search_engines": ["google", "bing"],
    }

    def test_recommendation_ai_calls_do_not_force_ollama_json_schema(self):
        source = Path(browser.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        for name in (
            "_build_ai_recommendation_plan",
            "_ask_ai_for_recommendation_options",
            "_run_recommendation_audit",
            "_build_ai_recommendation_recovery_queries",
            "_build_ai_verified_recommendation_reply",
        ):
            with self.subTest(function=name):
                rendered = ast.unparse(functions[name])
                self.assertIn("model_name='gemma3:12b'", rendered)
                self.assertNotIn("json_schema=", rendered)

    def test_empty_plain_json_output_retries_without_format_forcing(self):
        valid = {
            "topic": "straw cup",
            "search_queries": [
                "best straw cups expert reviews 2026 United States"
            ],
            "criteria": [],
            "audience_scope": "GENERAL_UNSPECIFIED",
            "audience": "general everyday users",
            "count_policy": "AI_DECIDES",
            "target_count": 2,
            "engine_policy": "PROFILE_DEFAULT",
            "engines": ["google", "bing"],
            "reason": "AI plan",
        }
        with patch.object(
            tools, "run_ai_prompt", side_effect=[None, valid]
        ) as model:
            plan = browser._build_ai_recommendation_plan(
                "给我推荐几个吸管杯", "", self.REGION
            )
        self.assertEqual(plan["topic"], "straw cup")
        self.assertEqual(model.call_count, 2)
        for call in model.call_args_list:
            self.assertNotIn("json_schema", call.kwargs)
            self.assertEqual(call.kwargs["model_name"], "gemma3:12b")
            self.assertEqual(call.kwargs["num_predict"], 1800)
        retry_packet = json.loads(model.call_args_list[1].args[1])
        self.assertIn("retry_instruction", retry_packet)

    def test_option_synthesis_retries_an_empty_gpt_result(self):
        sources = [
            {
                "index": 1,
                "domain": "review.example",
                "title": "Straw cup guide",
                "description": "Independent editorial guide.",
                "url": "https://review.example/straw-cups",
            }
        ]
        packet = {
            "original_user_request": "给我推荐几个吸管杯",
            "topic": "straw cup",
            "criteria": [],
            "audience_scope": "GENERAL_UNSPECIFIED",
            "audience": "general everyday users",
            "count_policy": "AI_DECIDES",
            "target_count": 2,
            "sources": sources,
        }
        valid = {
            "items": [
                {
                    "title": "Example Straw Cup",
                    "brand": "Example",
                    "summary": "Supported by the supplied independent guide.",
                    "source_indexes": [1],
                    "verification_queries": ["Example Straw Cup specifications"],
                }
            ],
            "reply": "我根据独立评测推荐这一款吸管杯。",
        }
        with patch.object(
            tools, "run_ai_prompt", side_effect=[None, valid]
        ) as model:
            options, reply = browser._ask_ai_for_recommendation_options(packet)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(len(options), 1)
        self.assertEqual(reply, valid["reply"])
        for call in model.call_args_list:
            self.assertNotIn("json_schema", call.kwargs)
            self.assertEqual(call.kwargs["model_name"], "gemma3:12b")
            self.assertEqual(call.kwargs["num_predict"], 1800)


if __name__ == "__main__":
    unittest.main()
