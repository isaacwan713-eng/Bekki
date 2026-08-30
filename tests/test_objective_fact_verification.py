import unittest
from unittest import mock

from nerv import objective_fact


class ObjectiveFactVerificationTests(unittest.TestCase):
    def _local_plan(self, **updates):
        plan = {
            "response_mode": "LOCAL_ANSWER",
            "interaction_mode": "TASK",
        }
        plan.update(updates)
        return plan

    def test_snh48_false_team_list_reaches_audit(self):
        self.assertTrue(
            objective_fact.should_audit(
                "请解释SNH48的分队、成员和剧场公演。",
                "固定分队包括M队、L队、C队、A队、B队、T队、X队。",
                plan=self._local_plan(),
            )
        )

    def test_user_challenge_reaches_audit_without_treating_user_as_authority(self):
        self.assertTrue(
            objective_fact.should_audit(
                "好像没有吧，你确定吗？",
                "我之前说的公开人物状态可能是对的。",
                plan=self._local_plan(),
            )
        )

    def test_public_death_claim_reaches_audit(self):
        self.assertTrue(
            objective_fact.should_audit(
                "柏木由纪死了吗？",
                "她已经去世。",
                plan=self._local_plan(),
            )
        )

    def test_verified_local_knowledge_skips_extra_audit(self):
        self.assertFalse(
            objective_fact.should_audit(
                "SNH48有哪些分队？",
                "已从验证知识回答。",
                local_knowledge_context="verified knowledge",
                plan=self._local_plan(),
            )
        )

    def test_personal_family_and_device_facts_remain_user_authoritative(self):
        for message in ("我的妈妈叫什么？", "我的电脑是什么型号？", "我的偏好是什么？"):
            with self.subTest(message=message):
                self.assertFalse(
                    objective_fact.should_audit(
                        message,
                        "这是用户自己的信息。",
                        plan=self._local_plan(),
                    )
                )

    def test_fast_local_tasks_skip_audit(self):
        cases = (
            ("你好", "你好呀！"),
            ("把这句话翻译成英文", "Here is the translation."),
            ("写一首关于雨的诗", "雨落在窗前。"),
            ("计算2+2", "4"),
        )
        for message, draft in cases:
            with self.subTest(message=message):
                self.assertFalse(
                    objective_fact.should_audit(
                        message,
                        draft,
                        plan=self._local_plan(),
                    )
                )

    def test_invalid_audit_fails_closed_to_verify(self):
        unload = mock.Mock()
        result = objective_fact.audit_draft(
            lambda *_args, **_kwargs: None,
            unload,
            "SNH48有哪些分队？",
            "M队、L队。",
        )
        self.assertEqual(result["decision"], "VERIFY")
        unload.assert_called_once_with("gemma4:e4b")

    def test_fact_plan_is_official_first(self):
        plan = objective_fact.fact_lookup_plan(
            self._local_plan(),
            {"claim": "SNH48 current team structure"},
        )
        self.assertEqual(plan["response_mode"], "FACT_LOOKUP")
        self.assertTrue(plan["needs_search"])
        self.assertEqual(plan["source_policy"], "official_first")
        self.assertEqual(plan["research_depth"], "direct_lookup")

    def test_fact_plan_preserves_high_risk_correction(self):
        plan = objective_fact.fact_lookup_plan(
            self._local_plan(risk="high"),
            {"claim": "A consequential contract claim"},
        )
        self.assertEqual(plan["risk"], "high")

    def test_only_ok_accepted_fact_results_are_usable(self):
        self.assertTrue(
            objective_fact.has_usable_fact_answer(
                {"status": "OK", "direct_reply": "verified"}
            )
        )
        self.assertTrue(
            objective_fact.has_usable_fact_answer(
                {
                    "status": "OK",
                    "answers": [{"accepted": True, "answer": "verified"}],
                }
            )
        )
        self.assertFalse(
            objective_fact.has_usable_fact_answer(
                {"status": "LIMITED_EVIDENCE", "answers": []}
            )
        )

    def test_ai_selects_only_exact_public_knowledge_claim_for_dispute(self):
        model = mock.Mock(return_value={
            "decision": "OBJECTIVE_DISPUTE",
            "disputed_knowledge_ids": ["knowledge-units", "unknown-id"],
            "claim_to_verify": "某组织当前正式单位的完整集合",
            "reason": "The user challenges the exact public unit-set claim.",
        })
        unload = mock.Mock()
        result = objective_fact.audit_knowledge_correction(
            model,
            unload,
            "不对，你刚才说的正式单位名单有误。",
            "Assistant: 该组织目前设有甲、乙、丙、丁四个正式单位。",
            [
                {
                    "id": "knowledge-units",
                    "subject": "某组织正式单位",
                    "claim": "该组织目前设有甲、乙、丙、丁四个正式单位。",
                    "knowledge_type": "reviewable",
                    "status": "verified",
                },
                {
                    "id": "knowledge-definition",
                    "subject": "组织术语定义",
                    "claim": "正式单位是内部组织单元。",
                    "knowledge_type": "stable",
                    "status": "verified",
                },
            ],
        )

        self.assertEqual(result["decision"], "OBJECTIVE_DISPUTE")
        self.assertEqual(
            result["disputed_knowledge_ids"],
            ["knowledge-units"],
        )
        self.assertEqual(
            model.call_args.args[0],
            "prompts/nerv_knowledge_correction_audit.txt",
        )
        unload.assert_called_once_with("gemma4:12b")

    def test_personal_correction_remains_user_authoritative(self):
        model = mock.Mock(return_value={
            "decision": "PERSONAL_AUTHORITY",
            "disputed_knowledge_ids": ["knowledge-public"],
            "claim_to_verify": "",
            "reason": "This is the user's own device fact.",
        })
        result = objective_fact.audit_knowledge_correction(
            model,
            mock.Mock(),
            "不对，我的电脑型号是另一款。",
            "Assistant: 你的电脑是某型号。",
            [{
                "id": "knowledge-public",
                "subject": "无关公开事实",
                "claim": "一条无关的公开事实。",
                "status": "verified",
            }],
        )
        self.assertEqual(result["decision"], "PERSONAL_AUTHORITY")
        self.assertEqual(result["disputed_knowledge_ids"], [])

    def test_correction_request_says_user_challenge_is_not_evidence(self):
        request = objective_fact.correction_fact_request(
            "你说的不对。",
            {
                "claim_to_verify": "某组织当前正式单位的完整集合",
            },
            [{
                "id": "knowledge-units",
                "subject": "某组织正式单位",
                "claim": "该组织目前设有四个正式单位。",
            }],
        )
        self.assertIn("not evidence", request)
        self.assertIn("knowledge-units", request)
        self.assertIn("Reverify", request)

    def test_replacement_mapper_is_ai_owned_and_exact_id_bounded(self):
        model = mock.Mock(return_value={
            "resolutions": [{
                "disputed_id": "knowledge-old-units",
                "replacement_ids": ["knowledge-new-units"],
                "reason": "The new record directly replaces the old set.",
            }],
            "reason": "Exact semantic mapping completed.",
        })
        mapping = objective_fact.audit_correction_replacements(
            model,
            mock.Mock(),
            [{
                "id": "knowledge-old-units",
                "subject": "某组织正式单位",
                "claim": "该组织设有四个正式单位。",
            }],
            [
                {
                    "id": "knowledge-new-units",
                    "subject": "某组织正式单位",
                    "claim": "该组织设有五个正式单位。",
                    "knowledge_type": "reviewable",
                },
                {
                    "id": "knowledge-definition",
                    "subject": "组织术语定义",
                    "claim": "正式单位是内部组织单元。",
                    "knowledge_type": "stable",
                },
            ],
            "Independent research answer text.",
        )
        self.assertEqual(
            mapping,
            {"knowledge-old-units": ["knowledge-new-units"]},
        )

    def test_replacement_ids_come_only_from_governed_fallback_metadata(self):
        result = objective_fact.replacement_knowledge_ids({
            "status": "OK",
            "knowledge_id": "top-level-id-must-not-count",
            "external_ai_fallback": {
                "knowledge_id": "knowledge-one",
                "knowledge_ids": ["knowledge-two", "knowledge-one"],
            },
        })
        self.assertEqual(result, ["knowledge-one", "knowledge-two"])


if __name__ == "__main__":
    unittest.main()
