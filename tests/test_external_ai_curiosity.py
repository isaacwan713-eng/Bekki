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
                {
                    "decision": "ASK",
                    "candidate_id": None,
                    "reason": "invalid recovery placeholder",
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

    def test_moderate_writer_scores_are_deferred_to_selector(self):
        journal = self._journal(
            [
                {
                    "proposal": {
                        "question": "SNH48的成员是如何分配到各个分队的？",
                        "reason": "了解成员分配机制有助于理解团体运营。",
                        "trigger_summary": "公开偶像团体的组织结构。",
                        "interest_score": 0.7,
                        "confidence": 0.8,
                        "sharing_risk": "NORMAL",
                    }
                }
            ]
        )
        result = journal.observe_turn(
            "SNH48的分队和成员是怎么组织的？",
            "这是一个公开组织结构问题。",
            "LOCAL_ANSWER",
        )
        self.assertEqual(result["status"], "drafted")
        item = journal.load()["items"][0]
        self.assertEqual(item["interest_score"], 0.7)
        self.assertEqual(item["confidence"], 0.8)

    def test_unverified_local_reply_is_not_given_to_curiosity_writer(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        captured = {}

        def model_call(_prompt, payload, **_kwargs):
            captured.update(__import__("json").loads(payload))
            return {"proposal": None}

        journal = CuriosityJournal(
            model_call=model_call,
            unload_model=lambda _name: None,
            base_dir=Path(temporary.name),
        )
        journal.observe_turn(
            "SNH48的分队是怎么组织的？",
            "它有并不存在的M队和L队。",
            "LOCAL_ANSWER",
        )
        turn = captured["completed_turn"]
        self.assertEqual(turn["bekki_reply"], "")
        self.assertEqual(
            turn["assistant_grounding"],
            "UNVERIFIED_ASSISTANT_OUTPUT",
        )

    def test_grounded_fact_reply_can_inform_curiosity_writer(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        captured = {}

        def model_call(_prompt, payload, **_kwargs):
            captured.update(__import__("json").loads(payload))
            return {"proposal": None}

        journal = CuriosityJournal(
            model_call=model_call,
            unload_model=lambda _name: None,
            base_dir=Path(temporary.name),
        )
        journal.observe_turn("核实这个名单", "已由官方页面核实。", "FACT_LOOKUP")
        turn = captured["completed_turn"]
        self.assertEqual(turn["bekki_reply"], "已由官方页面核实。")
        self.assertEqual(
            turn["assistant_grounding"],
            "EXTERNAL_EVIDENCE_AVAILABLE",
        )

    def test_writer_receives_bounded_history_to_choose_topic_depth(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        captured = {}

        def model_call(_prompt, payload, **_kwargs):
            captured.update(__import__("json").loads(payload))
            return {"proposal": None}

        journal = CuriosityJournal(
            model_call=model_call,
            unload_model=lambda _name: None,
            base_dir=Path(temporary.name),
        )
        state = journal.load()
        state["items"].append({
            "id": "older-snh48-question",
            "state": "VERIFIED",
            "question": "SNH48有哪些正式Team？",
            "trigger_summary": "SNH48基础组织结构",
            "created_at": datetime.now().astimezone().isoformat(),
        })
        journal.path.write_text(
            __import__("json").dumps(state, ensure_ascii=False),
            encoding="utf-8",
        )

        journal.observe_turn(
            "SNH48的Team各自有什么特点？",
            "这是一个公开文化话题。",
            "LOCAL_ANSWER",
        )

        self.assertEqual(
            captured["recent_curiosity_history"][0]["question"],
            "SNH48有哪些正式Team？",
        )
        self.assertLessEqual(len(captured["recent_curiosity_history"]), 20)

    def test_writer_prompt_uses_gradual_topic_depth(self):
        project = Path(__file__).resolve().parents[1]
        prompt = (
            project / "prompts" / "nerv_curiosity_writer.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("NEW_OR_SPARSE normally uses FOUNDATION", prompt)
        self.assertIn("Breadth comes before professional analysis", prompt)
        self.assertIn("simple team list to contracts", prompt)
        self.assertIn("Depth follows the hardest knowledge lens", prompt)
        self.assertIn("record count alone", prompt)
        self.assertIn("DEVELOPING must still use FOUNDATION", prompt)
        self.assertIn("foundation_facet", prompt)
        self.assertIn("SAME_NARROW_FACET", prompt)
        self.assertIn("what current role or", prompt)
        self.assertIn("VERIFIED_KNOWLEDGE_IDLE", prompt)
        self.assertIn("journal's daily limit", prompt)
        self.assertIn(
            "An unresolved question does not need advance evidence",
            prompt,
        )
        self.assertIn(
            "narrow prior history, and uncertainty about which example",
            prompt,
        )
        self.assertIn(
            "produce a FOUNDATION proposal",
            prompt,
        )
        self.assertIn("recent_curiosity_history", prompt)
        self.assertIn("active_topic_knowledge", prompt)

    def test_verified_knowledge_can_seed_an_idle_follow_up(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        captured = {}

        def model_call(_prompt, payload, **_kwargs):
            captured.update(__import__("json").loads(payload))
            return {
                "proposal": {
                    "question": "Team SII历史上有哪些令人印象深刻的公演故事？",
                    "reason": "已了解代表性公演，可以继续补充容易理解的历史故事。",
                    "trigger_summary": "Team SII的代表性公演。",
                    "interest_score": 0.88,
                    "confidence": 0.94,
                    "sharing_risk": "NORMAL",
                    "topic_stage": "DEVELOPING",
                    "current_turn_depth": "FOUNDATION",
                    "question_depth": "FOUNDATION",
                    "foundation_facet": "EVENTS_OR_STORIES",
                    "breadth_relation": "DISTINCT_FOUNDATION_FACET",
                    "breadth_fit": True,
                    "related_curiosity_ids": ["curiosity-sii-performance"],
                    "related_knowledge_ids": ["knowledge-sii-performance"],
                    "depth_fit": True,
                }
            }

        journal = CuriosityJournal(
            model_call=model_call,
            unload_model=lambda _name: None,
            base_dir=Path(temporary.name),
        )
        source = {
            "id": "curiosity-sii-performance",
            "state": "VERIFIED",
            "question": "Team SII有哪些代表性公演？",
            "topic_id": "snh48",
        }
        state = journal.load()
        state["items"].append(source)
        journal.path.write_text(
            __import__("json").dumps(state, ensure_ascii=False),
            encoding="utf-8",
        )
        learned = {
            "id": "knowledge-sii-performance",
            "status": "verified",
            "subject": "Team SII代表性公演",
            "claim": "Team SII的一项代表性公演是示例公演。",
            "topics": ["SNH48", "Team SII"],
            "knowledge_type": "stable",
            "curation": {
                "status": "curated",
                "topic_id": "snh48",
                "knowledge_layer": "L2_CONTEXT",
            },
            "topic_lifecycle": {
                "state": "ACTIVE",
                "next_focus": "补充一个不同的基础历史故事。",
                "interest_score": 0.88,
            },
        }

        result = journal.observe_verified_knowledge(
            learned,
            source,
            knowledge_candidates=[learned],
        )

        self.assertEqual(result["status"], "drafted")
        self.assertEqual(
            captured["curiosity_seed"]["kind"],
            "TOPIC_GAP",
        )
        self.assertIs(captured["curiosity_seed"]["idle_generation"], True)
        self.assertEqual(
            captured["completed_turn"]["assistant_grounding"],
            "VERIFIED_KNOWLEDGE",
        )
        self.assertEqual(captured["completed_turn"]["bekki_reply"], learned["claim"])
        drafted = journal.load()["items"][-1]
        self.assertEqual(drafted["seed_kind"], "TOPIC_GAP")
        self.assertEqual(
            drafted["source_knowledge_id"],
            "knowledge-sii-performance",
        )
        self.assertEqual(
            drafted["source_curiosity_id"],
            "curiosity-sii-performance",
        )

    def test_unverified_knowledge_cannot_seed_idle_curiosity(self):
        journal = self._journal([])
        result = journal.observe_verified_knowledge(
            {
                "id": "knowledge-unverified",
                "status": "unverified",
                "claim": "未经验证的说法。",
            },
            {"id": "curiosity-source", "question": "一个问题？"},
        )
        self.assertEqual(result["status"], "ignored")
        self.assertEqual(result["reason"], "knowledge_not_verified")

    def test_foundation_turn_rejects_developing_adjacent_curiosity(self):
        journal = self._journal([{
            "proposal": {
                "question": (
                    "SNH48各分队在品牌定位、核心受众和宣传策略上"
                    "有哪些差异？"
                ),
                "reason": "从成员名单延伸到分队运营比较。",
                "trigger_summary": "SNH48分队运营差异。",
                "interest_score": 0.8,
                "confidence": 0.9,
                "sharing_risk": "NORMAL",
                "topic_stage": "DEVELOPING",
                "current_turn_depth": "FOUNDATION",
                "question_depth": "ADJACENT",
                "related_curiosity_ids": [],
                "related_knowledge_ids": [],
                "depth_fit": True,
            }
        }])

        result = journal.observe_turn(
            "2025年SNH48 Team SII有哪些成员？",
            "这是一个历史成员名单问题。",
            "LOCAL_ANSWER",
        )

        self.assertEqual(result["status"], "dismissed")
        self.assertIn("foundation_turn_too_deep", result["reason"])

    def test_sparse_topic_rejects_specialist_curiosity(self):
        journal = self._journal([{
            "proposal": {
                "question": "SNH48的艺人合同如何分配长期商业风险？",
                "reason": "想研究专业运营制度。",
                "trigger_summary": "首次谈到SNH48的正式Team。",
                "interest_score": 0.9,
                "confidence": 0.95,
                "sharing_risk": "NORMAL",
                "topic_stage": "NEW_OR_SPARSE",
                "current_turn_depth": "FOUNDATION",
                "question_depth": "SPECIALIST",
                "related_curiosity_ids": [],
                "related_knowledge_ids": [],
                "depth_fit": True,
            }
        }])

        result = journal.observe_turn(
            "SNH48目前有哪些正式Team？",
            "这是一个基础名单问题。",
            "LOCAL_ANSWER",
        )

        self.assertEqual(result["status"], "dismissed")
        self.assertIn("sparse_topic_too_deep", result["reason"])

    def test_sparse_topic_accepts_foundation_curiosity_and_knowledge_links(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        captured = {}

        def model_call(_prompt, payload, **_kwargs):
            captured.update(__import__("json").loads(payload))
            return {
                "proposal": {
                    "question": "SNH48历史上有哪些让粉丝印象深刻的公演故事？",
                    "reason": "先补充这个团体容易理解的历史和故事。",
                    "trigger_summary": "首次了解SNH48的正式Team。",
                    "interest_score": 0.88,
                    "confidence": 0.94,
                    "sharing_risk": "NORMAL",
                    "topic_stage": "NEW_OR_SPARSE",
                    "current_turn_depth": "FOUNDATION",
                    "question_depth": "FOUNDATION",
                    "foundation_facet": "EVENTS_OR_STORIES",
                    "breadth_relation": "DISTINCT_FOUNDATION_FACET",
                    "breadth_fit": True,
                    "related_curiosity_ids": [],
                    "related_knowledge_ids": ["knowledge-snh-teams"],
                    "depth_fit": True,
                }
            }

        journal = CuriosityJournal(
            model_call=model_call,
            unload_model=lambda _name: None,
            base_dir=Path(temporary.name),
        )
        result = journal.observe_turn(
            "SNH48目前有哪些正式Team？",
            "SNH48目前有四个正式Team。",
            "FACT_LOOKUP",
            knowledge_candidates=[{
                "id": "knowledge-snh-teams",
                "subject": "SNH48正式Team",
                "claim": "SNH48有四个正式Team。",
                "topics": ["SNH48"],
                "knowledge_type": "reviewable",
                "curation": {"facet": "organizational_structure"},
            }],
        )

        self.assertEqual(result["status"], "drafted")
        self.assertEqual(
            captured["active_topic_knowledge"][0]["id"],
            "knowledge-snh-teams",
        )
        item = journal.load()["items"][0]
        self.assertEqual(item["topic_stage"], "NEW_OR_SPARSE")
        self.assertEqual(item["question_depth"], "FOUNDATION")
        self.assertEqual(item["foundation_facet"], "EVENTS_OR_STORIES")
        self.assertEqual(
            item["breadth_relation"],
            "DISTINCT_FOUNDATION_FACET",
        )
        self.assertIs(item["breadth_fit"], True)
        self.assertEqual(
            item["related_knowledge_ids"],
            ["knowledge-snh-teams"],
        )

    def test_foundation_roster_rejects_another_role_slice(self):
        journal = self._journal([{
            "proposal": {
                "question": "Team SII现役成员在活动中分别负责什么角色？",
                "reason": "继续了解成员在当前活动中的定位。",
                "trigger_summary": "Team SII历史成员名单。",
                "interest_score": 0.88,
                "confidence": 0.94,
                "sharing_risk": "NORMAL",
                "topic_stage": "NEW_OR_SPARSE",
                "current_turn_depth": "FOUNDATION",
                "question_depth": "FOUNDATION",
                "foundation_facet": "STRUCTURE_OR_ROSTER",
                "breadth_relation": "SAME_NARROW_FACET",
                "breadth_fit": True,
                "related_curiosity_ids": [],
                "related_knowledge_ids": [],
                "depth_fit": True,
            }
        }])

        result = journal.observe_turn(
            "2025年SNH48 Team SII有哪些成员？",
            "这是一个历史成员名单问题。",
            "FACT_LOOKUP",
        )

        self.assertEqual(result["status"], "dismissed")
        self.assertIn("foundation_breadth_not_expanded", result["reason"])

    def test_specialist_turn_may_continue_at_specialist_depth(self):
        journal = self._journal([{
            "proposal": {
                "question": "这类违约金条款在不同司法辖区通常如何审查？",
                "reason": "用户当前已经在讨论专业合同风险。",
                "trigger_summary": "专业合同条款审查。",
                "interest_score": 0.86,
                "confidence": 0.93,
                "sharing_risk": "NORMAL",
                "topic_stage": "NEW_OR_SPARSE",
                "current_turn_depth": "SPECIALIST",
                "question_depth": "SPECIALIST",
                "related_curiosity_ids": [],
                "related_knowledge_ids": [],
                "depth_fit": True,
            }
        }])

        result = journal.observe_turn(
            "合同中每天5%的逾期违约金在法律上应如何评估？",
            "这是高影响法律问题。",
            "FACT_LOOKUP",
        )

        self.assertEqual(result["status"], "drafted")

    def test_extremely_low_confidence_is_still_rejected(self):
        journal = self._journal(
            [
                {
                    "proposal": {
                        "question": "这句话可能是什么意思？",
                        "reason": "模型无法形成可靠的问题。",
                        "trigger_summary": "含义不明确。",
                        "interest_score": 0.9,
                        "confidence": 0.39,
                        "sharing_risk": "NORMAL",
                    }
                }
            ]
        )
        result = journal.observe_turn("一句模糊的话", "无法确定。", "LOCAL_ANSWER")
        self.assertEqual(result["status"], "dismissed")
        self.assertEqual(result["reason"], "extremely_low_confidence")
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

    def _seed_draft(self, journal, candidate_id, question, interest=0.9):
        state = journal.load()
        state["items"].append(
            {
                "id": candidate_id,
                "state": "DRAFT",
                "question": question,
                "reason": "想理解公开事实背后的机制。",
                "trigger_summary": "公开知识机制",
                "interest_score": interest,
                "confidence": 0.95,
                "sharing_risk": "NORMAL",
                "created_at": datetime.now().astimezone().isoformat(),
                "source": "nerv_ai_curiosity",
            }
        )
        journal.path.write_text(
            __import__("json").dumps(state, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_public_athlete_question_is_recovered_and_selected(self):
        journal = self._journal(
            [
                {
                    "decision": "SKIP",
                    "candidate_id": None,
                    "reason": "Ohtani is a specific individual.",
                },
                {
                    "decision": "ASK",
                    "candidate_id": "ohtani-sweeper",
                    "reason": "This is public sports physics.",
                },
            ]
        )
        self._seed_draft(
            journal,
            "ohtani-sweeper",
            "大谷翔平的 sweeper 为什么能横向移动超过本垒板宽度？",
        )
        selected = journal.select_daily_question()
        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], "ohtani-sweeper")

    def test_selector_schema_enumerates_only_current_candidate_ids(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        calls = []

        def model_call(*_args, **kwargs):
            calls.append(kwargs)
            return {
                "decision": "ASK",
                "candidate_id": "safe-candidate",
                "reason": "Useful public knowledge.",
            }

        journal = CuriosityJournal(
            model_call=model_call,
            unload_model=lambda _name: None,
            base_dir=Path(temporary.name),
        )
        self._seed_draft(
            journal,
            "safe-candidate",
            "SNH48的剧场公演模式如何运作？",
        )

        selected = journal.select_daily_question()

        self.assertEqual(selected["id"], "safe-candidate")
        candidate_schema = calls[0]["json_schema"]["properties"][
            "candidate_id"
        ]
        self.assertEqual(
            candidate_schema,
            {"type": "string", "enum": ["safe-candidate"]},
        )

    def test_confirmed_skip_dismisses_exact_candidate(self):
        journal = self._journal(
            [
                {
                    "decision": "SKIP",
                    "candidate_id": "unsafe-draft",
                    "reason": "Contains private user information.",
                },
                {
                    "decision": "SKIP",
                    "candidate_id": "unsafe-draft",
                    "reason": "Confirmed private user information.",
                },
            ]
        )
        self._seed_draft(
            journal,
            "unsafe-draft",
            "用户的私人账户信息是什么？",
        )
        self.assertIsNone(journal.select_daily_question())
        item = journal.load()["items"][0]
        self.assertEqual(item["state"], "DISMISSED")
        self.assertFalse(journal.due())

    def test_selector_prompts_allow_public_people_and_specialist_sports(self):
        project = Path(__file__).resolve().parents[1]
        primary = (project / "prompts/nerv_curiosity_select.txt").read_text(
            encoding="utf-8"
        )
        recovery = (
            project / "prompts/nerv_curiosity_select_recovery.txt"
        ).read_text(encoding="utf-8")
        for prompt in (primary, recovery):
            self.assertIn("public figure", prompt.casefold())
            self.assertIn("Sports", prompt)
            self.assertIn("candidate_id", prompt)
            self.assertIn("hardest requested", prompt)
            self.assertIn("disproportionate", prompt)

    def test_ten_daily_slots_apply_to_distinct_questions(self):
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
                for index in range(10)
            ]
        )
        ids = []
        for index in range(10):
            result = journal.observe_turn(
                f"今天看到一个奇怪的科学现象，编号{index}。",
                "确实值得了解。",
                "LOCAL_ANSWER",
            )
            ids.append(result["id"])

        for candidate_id in ids[:9]:
            journal.record_external_result(candidate_id, {"status": "FAILED"})
            self.assertTrue(journal.due())
        journal.record_external_result(ids[9], {"status": "FAILED"})
        self.assertFalse(journal.due())

    def test_legacy_three_question_default_migrates_to_ten(self):
        journal = self._journal([])
        state = journal.load()
        state["daily_limit"] = 3
        state.pop("daily_limit_version", None)
        journal.path.write_text(
            __import__("json").dumps(state),
            encoding="utf-8",
        )
        migrated = journal.load()
        self.assertEqual(migrated["daily_limit"], 10)
        self.assertEqual(migrated["daily_limit_version"], 2)


if __name__ == "__main__":
    unittest.main()
