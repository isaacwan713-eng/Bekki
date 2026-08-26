import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from nerv.curiosity import CuriosityJournal


class CuriosityJournalTests(unittest.TestCase):
    def _journal(self, responses):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        queue = list(responses)

        def model_call(*_args, **_kwargs):
            return queue.pop(0)

        journal = CuriosityJournal(
            model_call=model_call,
            unload_model=lambda _name: None,
            base_dir=Path(temporary.name),
        )
        return journal

    def test_normal_curiosity_is_drafted_then_answered_unverified(self):
        journal = self._journal(
            [
                {
                    "proposal": {
                        "question": "为什么猫会呼噜？",
                        "reason": "想理解这种声音的不同作用。",
                        "trigger_summary": "讨论了猫的行为。",
                        "interest_score": 0.91,
                        "confidence": 0.96,
                        "sharing_risk": "NORMAL",
                    }
                },
                {
                    "decision": "ASK",
                    "candidate_id": None,
                    "reason": "placeholder",
                },
            ]
        )
        drafted = journal.observe_turn("猫为什么会叫？", "可能有很多原因。", "LOCAL_ANSWER")
        self.assertEqual(drafted["status"], "drafted")
        state = journal.load()
        candidate_id = state["items"][0]["id"]

        # The selector must return an exact catalog ID; a null model choice is
        # safely ignored instead of selecting by position or keywords.
        self.assertIsNone(journal.select_daily_question())
        recorded = journal.record_external_result(
            candidate_id,
            {
                "status": "COMPLETED",
                "outbound_prompt": "为什么猫会呼噜？",
                "answer": "呼噜可能与交流、自我安抚等有关。",
            },
        )
        self.assertEqual(recorded["status"], "ANSWERED_UNVERIFIED")
        reply, count = journal.journal_reply("zh-CN")
        self.assertEqual(count, 1)
        self.assertIn("尚未验证", reply)
        self.assertIn("为什么猫会呼噜", reply)

    def test_sensitive_curiosity_is_rejected(self):
        journal = self._journal(
            [
                {
                    "proposal": {
                        "question": "用户住在哪里？",
                        "reason": "想知道位置。",
                        "trigger_summary": "用户提到出门。",
                        "interest_score": 0.99,
                        "confidence": 0.99,
                        "sharing_risk": "SENSITIVE",
                    }
                }
            ]
        )
        result = journal.observe_turn("我要出门", "路上小心。", "LOCAL_ANSWER")
        self.assertEqual(result["status"], "dismissed")
        self.assertEqual(journal.load()["items"], [])

    def test_chinese_turn_rejects_english_only_curiosity(self):
        journal = self._journal(
            [
                {
                    "proposal": {
                        "question": "Why do cats purr?",
                        "reason": "想理解这种声音的机制。",
                        "trigger_summary": "讨论了猫的行为。",
                        "interest_score": 0.91,
                        "confidence": 0.96,
                        "sharing_risk": "NORMAL",
                    }
                }
            ]
        )
        result = journal.observe_turn(
            "猫为什么会呼噜？",
            "可能与交流和自我安抚有关。",
            "LOCAL_ANSWER",
        )
        self.assertEqual(result["status"], "dismissed")
        self.assertEqual(journal.load()["items"], [])

    def test_chinese_turn_normalizes_english_internal_reason_and_trigger(self):
        journal = self._journal(
            [
                {
                    "proposal": {
                        "question": "为什么袋熊的粪便呈方形？",
                        "reason": (
                            "The unusual shape of koala feces sparks curiosity."
                        ),
                        "trigger_summary": (
                            "Animal physiology and unusual biological adaptations."
                        ),
                        "interest_score": 0.7,
                        "confidence": 0.9,
                        "sharing_risk": "NORMAL",
                    }
                }
            ]
        )
        result = journal.observe_turn(
            "我刚知道袋熊拉出来的便便竟然是方形的，感觉很奇怪。",
            "确实是很特别的生物现象。",
            "LOCAL_ANSWER",
        )
        self.assertEqual(result["status"], "drafted")
        item = journal.load()["items"][0]
        self.assertEqual(item["reason"], "这个问题来自刚才的对话，值得进一步了解。")
        self.assertEqual(
            item["trigger_summary"],
            "Animal physiology and unusual biological adaptations.",
        )

    def test_failed_attempt_prevents_repeated_browser_opening_today(self):
        journal = self._journal(
            [
                {
                    "proposal": {
                        "question": "树木如何在冬天保护细胞？",
                        "reason": "这个适应机制很有趣。",
                        "trigger_summary": "谈到冬天的树。",
                        "interest_score": 0.9,
                        "confidence": 0.95,
                        "sharing_risk": "NORMAL",
                    }
                }
            ]
        )
        drafted = journal.observe_turn("冬天的树", "它们会休眠。", "LOCAL_ANSWER")
        self.assertTrue(journal.due())
        journal.record_external_result(
            drafted["id"],
            {"status": "LOGIN_REQUIRED"},
        )
        self.assertFalse(journal.due())
        item = journal.load()["items"][0]
        self.assertEqual(item["state"], "DRAFT")
        self.assertEqual(
            journal._local_date(item["last_attempt_at"]),
            datetime.now().astimezone().date().isoformat(),
        )

    def test_three_daily_slots_apply_to_distinct_questions(self):
        journal = self._journal(
            [
                {
                    "proposal": {
                        "question": f"为什么这种现象会发生？编号{index}",
                        "reason": "想理解背后的公共科学机制。",
                        "trigger_summary": f"公共科学现象{index}",
                        "interest_score": 0.8,
                        "confidence": 0.9,
                        "sharing_risk": "NORMAL",
                    }
                }
                for index in range(3)
            ]
        )
        ids = []
        for index in range(3):
            result = journal.observe_turn(
                f"今天看到一个奇怪的科学现象，编号{index}。",
                "确实值得了解。",
                "LOCAL_ANSWER",
            )
            ids.append(result["id"])

        journal.record_external_result(ids[0], {"status": "FAILED"})
        self.assertTrue(journal.due())
        journal.record_external_result(ids[1], {"status": "FAILED"})
        self.assertTrue(journal.due())
        journal.record_external_result(ids[2], {"status": "FAILED"})
        self.assertFalse(journal.due())


if __name__ == "__main__":
    unittest.main()
