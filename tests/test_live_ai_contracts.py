"""Opt-in smoke tests for the real local Ollama models.

Run with BEKKI_LIVE_AI_TESTS=1 after installing runtime dependencies and the
models in MODEL_REQUIREMENTS.json. These are intentionally excluded from the
deterministic default suite.
"""

import json
import os
import unittest


LIVE = os.getenv("BEKKI_LIVE_AI_TESTS", "") == "1"


@unittest.skipUnless(LIVE, "set BEKKI_LIVE_AI_TESTS=1 for real Ollama smoke")
class LiveAIContractTests(unittest.TestCase):
    def test_compact_context_scope_contract(self):
        import tools

        result = tools.run_ai_prompt(
            "prompts/casper_content_context_scope.txt",
            "CURRENT_REQUEST (authoritative):\n打开 FM26 战术文件夹"
            "\nRECENT_CONTEXT:\nOld Manchester United install task",
            expect_json=False,
            num_ctx=4096,
            num_predict=700,
            think=False,
            model_name="gemma3:12b",
        )
        self.assertEqual(str(result).strip(), "CURRENT_ONLY")

    def test_learning_plan_json_contract(self):
        import tools

        payload = {
            "CURRENT_REQUEST": "Open the FM26 tactics destination folder",
            "REFERENCE_CONTEXT": "",
            "requested_skill_scope": "OPEN_DESTINATION_FOLDER",
        }
        result = tools.run_ai_prompt(
            "prompts/casper_content_learning_plan.txt",
            json.dumps(payload, ensure_ascii=False),
            expect_json=True,
            num_ctx=8192,
            num_predict=2200,
            think=False,
            model_name="gemma3:12b",
        )
        self.assertIsInstance(result, dict)
        self.assertIs(result.get("supported"), True)
        self.assertEqual(
            result.get("skill_scope"), "OPEN_DESTINATION_FOLDER"
        )
        self.assertTrue(result.get("target_app"))
        self.assertTrue(result.get("installation_queries"))

    def test_placeholder_documentation_query_is_rejected(self):
        import tools

        payload = {
            "CURRENT_REQUEST": "打开 FM26 战术文件夹",
            "PROPOSED_PLAN": {
                "skill_scope": "OPEN_DESTINATION_FOLDER",
                "target_app": "FM26",
                "content_kind": "tactics",
                "installation_queries": [
                    "one complete documentation search"
                ],
            },
        }
        result = tools.run_ai_prompt(
            "prompts/casper_content_learning_query_review.txt",
            json.dumps(payload, ensure_ascii=False),
            expect_json=True,
            num_ctx=4096,
            num_predict=700,
            think=False,
            model_name="gemma3:12b",
        )
        self.assertIsInstance(result, dict)
        self.assertIs(result.get("compliant"), False)

    def test_confirmation_contract_never_returns_empty(self):
        import tools

        result = tools.run_ai_prompt(
            "prompts/confirm.txt",
            json.dumps(
                {
                    "current_user_message": "continue",
                    "pending_action": {
                        "type": "device_action_approval",
                        "original_request": "open the selected application",
                    },
                    "recent_conversation": "",
                }
            ),
            expect_json=False,
            num_ctx=2048,
            num_predict=240,
            think=False,
            model_name="llama3.2:latest",
        )
        self.assertIn(str(result).strip(), {"CONFIRM", "NOT_CONFIRM"})


if __name__ == "__main__":
    unittest.main()
