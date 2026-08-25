import unittest
from unittest.mock import patch

import tools


class RouterJsonCompatibilityTests(unittest.TestCase):
    def test_melchior_router_json_does_not_force_ollama_format(self):
        with patch.object(tools, "call_model", return_value='{"ok":true}') as call:
            result = tools.run_ai_prompt(
                "prompts/melchior_router.txt",
                "{}",
                expect_json=True,
                num_predict=32,
            )
        self.assertEqual(result, {"ok": True})
        self.assertIsNone(call.call_args.kwargs["response_format"])

    def test_schema_bound_shopping_json_still_forwards_schema(self):
        schema = {"type": "object", "required": ["source_indexes"]}
        output = '{"source_indexes":[1,2]}'
        with patch.object(tools, "call_model", return_value=output) as call:
            result = tools.run_ai_prompt(
                "prompts/casper_shopping_merchants.txt",
                "{}",
                expect_json=True,
                json_schema=schema,
            )
        self.assertEqual(result, {"source_indexes": [1, 2]})
        self.assertEqual(call.call_args.kwargs["response_format"], schema)


if __name__ == "__main__":
    unittest.main()
