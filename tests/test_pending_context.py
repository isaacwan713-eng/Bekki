import sys
import types
import unittest
from unittest.mock import Mock, patch

from casper import pending_context


class PendingContextTests(unittest.TestCase):
    def _classify(self, outputs, message="打开目标内容文件夹"):
        model = Mock(side_effect=outputs)
        tools_stub = types.SimpleNamespace(run_ai_prompt=model)
        pending = {
            "type": "content_learning_continue",
            "original_request": "搜索、下载并安装旧内容",
            "approval_payload": {
                "verification_kind": "learned_destination"
            },
        }
        with patch.dict(sys.modules, {"tools": tools_stub}):
            result = pending_context.classify(
                message, pending, "Earlier unrelated operation"
            )
        return result, model

    def test_complete_same_topic_command_is_ai_classified_as_new(self):
        result, model = self._classify(["NEW_REQUEST"])
        self.assertEqual(result, "NEW_REQUEST")
        payload = model.call_args.args[1]
        self.assertIn('"current_request"', payload)
        self.assertIn('"active_checkpoint"', payload)

    def test_short_continue_can_answer_the_checkpoint(self):
        result, _model = self._classify(
            ["CHECKPOINT_REPLY"], message="继续"
        )
        self.assertEqual(result, "CHECKPOINT_REPLY")

    def test_invalid_primary_uses_distinct_retry_then_fails_closed(self):
        result, model = self._classify(["", "not-a-relation"])
        self.assertEqual(result, "AMBIGUOUS")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_pending_turn_relation_retry.txt",
        )


if __name__ == "__main__":
    unittest.main()
