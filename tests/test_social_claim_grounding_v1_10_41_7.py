import ast
from pathlib import Path
import tempfile
import unittest

import melchior
from nerv.curiosity import CuriosityJournal


ROOT = Path(__file__).resolve().parents[1]


def _main_failure_functions():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    names = {
        "_claim_check_failure_reply",
        "_social_research_failure_reply",
    }
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {}
    exec(
        compile(ast.fix_missing_locations(ast.Module(nodes, [])), "main.py", "exec"),
        namespace,
    )
    return namespace


class PlatformlessSocialRoutingV110417Tests(unittest.TestCase):
    @staticmethod
    def _magi_claim_route():
        return {
            "lane": "SEARCH",
            "confidence": 0.9,
            "reason": "The user asked whether a public rumor is true.",
            "social_scope": "OTHER",
            "social_platforms": [],
            "search_scope": "CLAIM_CHECK",
            "recommendation_domain": None,
            "local_knowledge_sufficiency": "NONE",
        }

    def test_platformless_social_plan_preserves_magi_claim_scope(self):
        plan = melchior._normalize_plan(
            {
                "response_mode": "SOCIAL_RESEARCH",
                "social_platforms": [],
                "reason": "Public rumor discussion.",
            }
        )
        result = melchior._reconcile_platformless_social_plan(
            plan,
            self._magi_claim_route(),
            "卡黄闹翻了吗？",
        )
        self.assertEqual(result["response_mode"], "CLAIM_CHECK")
        self.assertEqual(result["social_platforms"], [])
        self.assertEqual(
            result["claim_to_verify"],
            "卡黄闹翻了吗？",
        )
        self.assertEqual(result["research_depth"], "3_5_7")

    def test_named_social_platform_remains_platform_native(self):
        plan = melchior._normalize_plan(
            {
                "response_mode": "SOCIAL_RESEARCH",
                "social_platforms": ["bilibili"],
            }
        )
        result = melchior._reconcile_platformless_social_plan(
            plan,
            self._magi_claim_route(),
            "在 B 站搜卡黄",
        )
        self.assertEqual(result["response_mode"], "SOCIAL_RESEARCH")
        self.assertEqual(result["social_platforms"], ["bilibili"])

    def test_plan_request_applies_reconciliation_to_both_router_paths(self):
        source = (ROOT / "melchior.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(
            source.count("plan = _reconcile_platformless_social_plan("),
            2,
        )


class ResearchFailureBoundaryV110417Tests(unittest.TestCase):
    def setUp(self):
        self.contract = _main_failure_functions()

    def test_claim_check_insufficient_evidence_cannot_become_a_conclusion(self):
        reply = self.contract["_claim_check_failure_reply"](
            {
                "status": "INSUFFICIENT_EVIDENCE",
                "judgment": {
                    "need_more_sources": True,
                    "canonical_answer": None,
                },
            }
        )
        self.assertIn("不能判断", reply)
        self.assertIn("搜索未完成不等于传闻为假", reply)

    def test_supported_claim_check_can_reach_final_writer(self):
        reply = self.contract["_claim_check_failure_reply"](
            {
                "status": "OK",
                "judgment": {
                    "need_more_sources": False,
                    "canonical_answer": "来源之间存在可解释的一致结论。",
                },
            }
        )
        self.assertIsNone(reply)

    def test_no_platform_social_result_fails_closed(self):
        reply = self.contract["_social_research_failure_reply"](
            {"status": "NO_PLATFORM", "results": []}
        )
        self.assertIn("实际上没有完成社媒搜索", reply)
        self.assertIn("不能", reply)

    def test_casper_marks_empty_research_as_limited_evidence(self):
        source = (ROOT / "casper" / "core.py").read_text(encoding="utf-8")
        for status in (
            "INSUFFICIENT_EVIDENCE",
            "NO_PLATFORM",
            "QUERY_UNAVAILABLE",
            "NO_READABLE_SOCIAL_PAGE",
        ):
            self.assertIn('"' + status + '"', source)


class TextAnchoredPeopleV110417Tests(unittest.TestCase):
    def test_post_prompt_preserves_named_co_subjects_without_face_guessing(self):
        prompt = (ROOT / "prompts" / "social_post_introduction.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("preserve all of them in primary_subject", prompt)
        self.assertIn("Do not reduce the overall", prompt)
        self.assertIn("Never use face recognition", prompt)
        self.assertIn("left/right", prompt)

    def test_visual_overview_keeps_text_identity_separate_from_pixels(self):
        prompt = (ROOT / "prompts" / "social_visual_extract.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("named co-subjects", prompt)
        self.assertIn("without a readable", prompt)
        self.assertIn("text-grounded naming separate", prompt)


class CompactCuriosityRecoveryV110417Tests(unittest.TestCase):
    @staticmethod
    def _proposal():
        return {
            "proposal": {
                "question": "李艺彤与黄婷婷有哪些具有代表性的公开合作舞台？",
                "reason": "刚才的关系话题留下了公开合作经历这一背景问题。",
                "trigger_summary": "公开人物组合的合作舞台",
                "interest_score": 0.8,
                "confidence": 0.8,
                "sharing_risk": "NORMAL",
                "topic_stage": "NEW_OR_SPARSE",
                "current_turn_depth": "FOUNDATION",
                "question_depth": "FOUNDATION",
                "foundation_facet": "WORKS_OR_PERFORMANCES",
                "breadth_relation": "DISTINCT_FOUNDATION_FACET",
                "breadth_fit": True,
                "related_curiosity_ids": [],
                "related_knowledge_ids": [],
                "depth_fit": True,
            }
        }

    def test_invalid_writer_uses_short_recovery_prompt_and_4096_context(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        calls = []

        def model_call(prompt_path, input_text, **kwargs):
            calls.append((prompt_path, input_text, kwargs))
            return None if len(calls) == 1 else self._proposal()

        journal = CuriosityJournal(
            model_call=model_call,
            unload_model=lambda _name: None,
            base_dir=Path(temporary.name),
        )
        result = journal.observe_turn(
            "卡黄是闹翻了吗？",
            "可核实资料中的卡黄指李艺彤与黄婷婷。",
            "CLAIM_CHECK",
        )
        self.assertEqual(result["status"], "drafted")
        self.assertEqual(calls[1][0], "prompts/nerv_curiosity_writer_recover.txt")
        self.assertEqual(calls[1][2]["num_ctx"], 4096)
        self.assertEqual(calls[1][2]["num_predict"], 1600)
        recovery_packet = calls[1][1]
        self.assertIn("FIRST_WRITER_OUTPUT_WAS_INVALID_OR_TRUNCATED", recovery_packet)

    def test_recovery_prompt_is_materially_smaller_than_primary(self):
        primary = (ROOT / "prompts" / "nerv_curiosity_writer.txt").read_bytes()
        recovery = (
            ROOT / "prompts" / "nerv_curiosity_writer_recover.txt"
        ).read_bytes()
        self.assertLess(len(recovery), len(primary) // 3)
        text = " ".join(recovery.decode("utf-8").split())
        self.assertIn("one compound label", text)
        self.assertIn("do not ask for those identities again", text)


if __name__ == "__main__":
    unittest.main()
