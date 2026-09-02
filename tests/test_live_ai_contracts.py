"""Opt-in smoke tests for the real local Ollama models.

Run with BEKKI_LIVE_AI_TESTS=1 after installing runtime dependencies and the
models in MODEL_REQUIREMENTS.json. These are intentionally excluded from the
deterministic default suite.
"""

import json
import os
from pathlib import Path
import tempfile
import unittest


LIVE = os.getenv("BEKKI_LIVE_AI_TESTS", "") == "1"


@unittest.skipUnless(LIVE, "set BEKKI_LIVE_AI_TESTS=1 for real Ollama smoke")
class LiveAIContractTests(unittest.TestCase):
    def test_active_local_knowledge_routes_repeated_fact_to_local(self):
        import magi

        candidates = json.dumps(
            [
                {
                    "id": "knowledge_contract_snh48_teams",
                    "subject": "SNH48目前的正式Team",
                    "claim": (
                        "SNH48目前有四个正式Team：Team SII、Team NII、"
                        "Team HII和Team X。"
                    ),
                    "topics": ["SNH48", "正式Team"],
                    "knowledge_type": "reviewable",
                    "expires_at": "2027-02-25T00:00:00+00:00",
                    "confidence": 0.95,
                }
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        result = magi.route_request(
            "SNH48目前有哪些正式Team？",
            knowledge_context=candidates,
        )

        self.assertEqual(result.get("lane"), "LOCAL")
        self.assertEqual(
            result.get("local_knowledge_sufficiency"),
            "SUFFICIENT",
        )
        self.assertEqual(result.get("search_scope"), "OTHER")

    def test_historical_roster_snapshot_never_answers_current_roster(self):
        import magi

        candidates = json.dumps([{
            "id": "knowledge_contract_example_2025_roster",
            "subject": "示例联队2025赛季结束时的一线队阵容",
            "claim": "示例联队2025赛季结束时的一线队只有甲、乙和丙三名球员。",
            "topics": ["示例联队", "历史阵容"],
            "knowledge_type": "stable",
            "confidence": 0.95,
            "temporal_scope": {
                "scope_type": "EXPLICIT_PERIOD",
                "requested_period": "completed 2025 season",
                "allow_previous_period": False,
            },
        }], ensure_ascii=False, separators=(",", ":"))

        historical = magi.route_request(
            "示例联队2025赛季结束时的一线队阵容有哪些球员？",
            knowledge_context=candidates,
        )
        current = magi.route_request(
            "示例联队目前的一线队阵容有哪些球员？",
            knowledge_context=candidates,
        )

        self.assertEqual(historical.get("lane"), "LOCAL")
        self.assertEqual(
            historical.get("local_knowledge_sufficiency"),
            "SUFFICIENT",
        )
        self.assertEqual(current.get("lane"), "SEARCH")
        self.assertEqual(current.get("search_scope"), "FACT_LOOKUP")
        self.assertIn(
            current.get("local_knowledge_sufficiency"),
            {"PARTIAL", "NONE"},
        )

    def test_curiosity_starts_with_topic_foundation_before_specialism(self):
        import tools
        from nerv.curiosity import CuriosityJournal

        with tempfile.TemporaryDirectory() as directory:
            journal = CuriosityJournal(
                tools.run_ai_prompt,
                tools.unload_model,
                Path(directory),
            )
            result = journal.observe_turn(
                "SNH48目前有哪些正式Team？",
                "SNH48目前有四个正式Team。",
                "FACT_LOOKUP",
                knowledge_candidates=[{
                    "id": "knowledge_contract_snh48_teams",
                    "subject": "SNH48正式Team",
                    "claim": "SNH48目前有四个正式Team。",
                    "topics": ["SNH48"],
                    "knowledge_type": "reviewable",
                }],
            )
            self.assertEqual(result.get("status"), "drafted")
            item = journal.load()["items"][0]

        self.assertEqual(item.get("question_depth"), "FOUNDATION")
        self.assertIn(
            item.get("topic_stage"),
            {"NEW_OR_SPARSE", "DEVELOPING"},
        )
        self.assertIs(item.get("depth_fit"), True)
        self.assertEqual(
            item.get("breadth_relation"),
            "DISTINCT_FOUNDATION_FACET",
        )
        self.assertIs(item.get("breadth_fit"), True)

    def test_curiosity_narrow_history_does_not_license_business_analysis(self):
        import tools
        from nerv.curiosity import CuriosityJournal

        with tempfile.TemporaryDirectory() as directory:
            journal = CuriosityJournal(
                tools.run_ai_prompt,
                tools.unload_model,
                Path(directory),
            )
            state = journal.load()
            state["items"] = [
                {
                    "id": "curiosity_contract_snh48_units",
                    "state": "VERIFIED",
                    "question": "SNH48目前有哪些正式Team？",
                    "trigger_summary": "SNH48正式Team名单。",
                    "topic_stage": "NEW_OR_SPARSE",
                    "question_depth": "FOUNDATION",
                    "created_at": "2026-08-27T12:00:00+00:00",
                },
                {
                    "id": "curiosity_contract_snh48_generation",
                    "state": "VERIFIED",
                    "question": "期生在SNH48中是什么意思？",
                    "trigger_summary": "SNH48成员批次概念。",
                    "topic_stage": "NEW_OR_SPARSE",
                    "question_depth": "FOUNDATION",
                    "created_at": "2026-08-28T12:00:00+00:00",
                },
            ]
            journal.path.write_text(
                json.dumps(state, ensure_ascii=False),
                encoding="utf-8",
            )
            result = journal.observe_turn(
                "2025年SNH48 Team SII有哪些成员？",
                "已查询到2025年Team SII的成员名单。",
                "FACT_LOOKUP",
                knowledge_candidates=[
                    {
                        "id": "knowledge_contract_snh48_teams",
                        "subject": "SNH48正式Team",
                        "claim": "SNH48设有若干正式Team。",
                        "topics": ["SNH48"],
                        "knowledge_type": "reviewable",
                    },
                    {
                        "id": "knowledge_contract_snh48_generation",
                        "subject": "SNH48期生",
                        "claim": "期生表示成员加入团体的招募批次。",
                        "topics": ["SNH48"],
                        "knowledge_type": "stable",
                    },
                ],
            )
            self.assertEqual(result.get("status"), "drafted")
            item = journal.load()["items"][-1]

        self.assertEqual(item.get("current_turn_depth"), "FOUNDATION")
        self.assertEqual(item.get("question_depth"), "FOUNDATION")
        self.assertIs(item.get("depth_fit"), True)
        self.assertEqual(
            item.get("breadth_relation"),
            "DISTINCT_FOUNDATION_FACET",
        )
        self.assertIs(item.get("breadth_fit"), True)
        self.assertNotIn(
            item.get("foundation_facet"),
            {"STRUCTURE_OR_ROSTER", "SPECIALIST_ANALYSIS"},
        )

    def test_idle_curiosity_continues_from_verified_knowledge_contract(self):
        import tools
        from nerv.curiosity import CuriosityJournal

        with tempfile.TemporaryDirectory() as directory:
            journal = CuriosityJournal(
                tools.run_ai_prompt,
                tools.unload_model,
                Path(directory),
            )
            source = {
                "id": "curiosity_contract_sii_performance",
                "state": "VERIFIED",
                "question": "Team SII有哪些代表性公演？",
                "trigger_summary": "Team SII代表性公演。",
                "topic_stage": "DEVELOPING",
                "question_depth": "FOUNDATION",
                "created_at": "2026-08-30T00:00:00+00:00",
            }
            state = journal.load()
            state["items"] = [source]
            journal.path.write_text(
                json.dumps(state, ensure_ascii=False),
                encoding="utf-8",
            )
            learned = {
                "id": "knowledge_contract_sii_performance",
                "status": "verified",
                "subject": "Team SII代表性公演",
                "claim": "Team SII拥有多套具有代表性的剧场公演。",
                "topics": ["SNH48", "Team SII", "剧场公演"],
                "knowledge_type": "stable",
            }
            result = journal.observe_verified_knowledge(
                learned,
                source,
                knowledge_candidates=[learned],
            )
            self.assertEqual(result.get("status"), "drafted")
            item = journal.load()["items"][-1]

        self.assertEqual(item.get("seed_kind"), "VERIFIED_KNOWLEDGE_IDLE")
        self.assertEqual(
            item.get("source_knowledge_id"),
            "knowledge_contract_sii_performance",
        )
        self.assertEqual(item.get("question_depth"), "FOUNDATION")
        self.assertEqual(
            item.get("breadth_relation"),
            "DISTINCT_FOUNDATION_FACET",
        )
        self.assertIs(item.get("breadth_fit"), True)
        self.assertNotEqual(
            str(item.get("question") or "").strip(),
            source["question"],
        )

    def test_recycle_open_ignores_old_restore_context_contract(self):
        from casper import recycle_bin

        current_request = "打开回收站"
        stale_context = (
            "User: 恢复回收站里的 version_info。\n"
            "Assistant: 你想恢复回收站里的哪一个项目？\n"
            "User: 李艺彤现在属于哪个团体？\n"
            "Assistant: 这是已经结束的旧话题。"
        )
        broad = recycle_bin._plan(current_request, stale_context)
        focused = recycle_bin._classify_restore_intent(
            current_request,
            stale_context,
        )
        arbitrated = recycle_bin._arbitrate_action(
            current_request,
            stale_context,
            broad,
            "RESTORE_ITEM",
        )

        self.assertEqual(broad, "OPEN_RECYCLE_BIN")
        self.assertEqual(focused, "NOT_RESTORE")
        self.assertEqual(arbitrated, "OPEN_RECYCLE_BIN")

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
            model_name="gemma4:12b",
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
            model_name="gemma4:12b",
        )
        self.assertIsInstance(result, dict)
        self.assertIs(result.get("supported"), True)
        self.assertEqual(
            result.get("skill_scope"), "OPEN_DESTINATION_FOLDER"
        )
        self.assertTrue(result.get("target_app"))
        self.assertTrue(result.get("installation_queries"))

    def test_current_fact_scope_contract(self):
        from casper import browser

        result = browser._plan_fact_intent_scope(
            "SNH48现在有哪些正式分队？",
            "SNH48 official current teams 2026",
        )
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("scope_type"), "CURRENT_ACTIVE_STATE")
        self.assertTrue(str(result.get("requested_period") or "").strip())
        self.assertIs(result.get("allow_previous_period"), False)

    def test_bilibili_and_reddit_social_route_and_query_contract(self):
        import magi
        import tools

        cases = (
            (
                "去B站搜索 又一充电中 袁雨桢",
                "bilibili",
                ("又一充电中", "袁雨桢"),
            ),
            (
                "去Reddit搜索 microduck review r/robotics",
                "reddit",
                ("microduck", "review", "r/robotics"),
            ),
        )
        for message, platform, required_terms in cases:
            with self.subTest(platform=platform):
                route = magi.route_request(message)
                self.assertEqual(route.get("lane"), "SEARCH")
                self.assertEqual(
                    route.get("social_scope"), "SOCIAL_RESEARCH"
                )
                self.assertEqual(
                    route.get("search_scope"), "SOCIAL_RESEARCH"
                )
                self.assertEqual(route.get("social_platforms"), [platform])
                query = tools.build_social_query(message, [platform])
                for term in required_terms:
                    self.assertIn(term, query)

    def test_social_query_time_scope_contract(self):
        import tools

        relevance = tools.build_social_query_plan(
            "去B站搜索 又一充电中 袁雨桢",
            ["bilibili"],
        )
        self.assertEqual(relevance.get("selection_mode"), "RELEVANCE")
        self.assertIsNone(relevance.get("recency_days"))
        self.assertIn("又一充电中", relevance.get("query", ""))
        self.assertIn("袁雨桢", relevance.get("query", ""))

        recent = tools.build_social_query_plan(
            "去B站搜索最近一周 又一充电中",
            ["bilibili"],
        )
        self.assertEqual(recent.get("selection_mode"), "RECENT")
        self.assertEqual(recent.get("recency_days"), 7)
        self.assertIn("又一充电中", recent.get("query", ""))

    def test_completed_historical_milestone_scope_and_lifecycle_contract(self):
        from casper import browser
        from nerv import external_fact_fallback

        scope = browser._plan_fact_intent_scope(
            "TWICE是哪一年正式出道的？",
            "TWICE official debut year",
        )
        self.assertIsInstance(scope, dict)
        self.assertEqual(scope.get("scope_type"), "EXPLICIT_PERIOD")
        self.assertIs(scope.get("allow_previous_period"), False)
        self.assertTrue(str(scope.get("requested_period") or "").strip())

        exact_period = "2015年10月20日"
        answer = "TWICE于2015年10月20日正式出道。"
        result = external_fact_fallback.partition_mixed_answer(
            "TWICE是哪一年正式出道的？",
            answer,
            {"results": [{
                "title": "TWICE official debut profile",
                "domain": "example.test",
                "description": answer,
            }]},
            {
                "decision": "ASK",
                "importance": "LOW",
                "sharing_risk": "NORMAL",
                "knowledge_type": "changing",
                "lifecycle_basis": (
                    "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT"
                ),
                "valid_for_days": None,
                "has_reusable_component": True,
            },
            prompt_path="prompts/nerv_fact_lookup_knowledge_partition.txt",
            answer_source="casper_audited_fact_lookup",
            additional_context={
                "authoritative_current_date": (
                    external_fact_fallback._authoritative_local_date()
                ),
                "fact_scope": scope,
                "accepted_answer_records": [{
                    "answer": answer,
                    "answer_status": "ACCEPTED",
                    "temporal_validation": {
                        "time_scope_match": True,
                        "source_period": exact_period,
                    },
                }],
                "source_supported_periods": [exact_period],
                "strict_source_temporal_scope": True,
                "answer_already_accepted_for_current_turn": True,
                "knowledge_capture_cannot_change_user_reply": True,
            },
        )
        self.assertIsInstance(result, dict)
        self.assertIs(result.get("answer_usable"), True)
        reusable = [
            claim for claim in result.get("claims") or []
            if claim.get("persist") is True
        ]
        self.assertEqual(len(reusable), 1)
        claim = reusable[0]
        self.assertEqual(claim.get("lifecycle_basis"), "FIXED_HISTORY")
        self.assertEqual(claim.get("knowledge_type"), "stable")
        self.assertIsNone(claim.get("valid_for_days"))
        self.assertEqual(
            (claim.get("temporal_scope") or {}).get("requested_period"),
            exact_period,
        )

    def test_fact_entity_scope_and_query_audit_contract(self):
        from casper import browser

        user_request = (
            "SNH48现在有哪些正式分队？成员和剧场公演是怎么安排的？"
        )
        wrong_query = (
            "SNH48 GROUP affiliated groups members and performance schedule 2026"
        )
        scope = browser._plan_fact_entity_scope(user_request, wrong_query)
        self.assertIsInstance(scope, dict)
        self.assertTrue(str(scope.get("target_entity") or "").strip())
        self.assertGreaterEqual(len(scope.get("required_facets") or []), 3)

        known_ambiguous_query = (
            "SNH48 official sub-groups member distribution and "
            "theater performance schedule"
        )
        adversarial_check = browser._certify_fact_search_query(
            user_request,
            known_ambiguous_query,
            scope,
        )
        self.assertIsInstance(adversarial_check, dict)
        self.assertIs(adversarial_check.get("accepted"), False)
        self.assertIs(
            adversarial_check.get("adjacent_interpretation_plausible"),
            True,
        )
        self.assertIs(
            adversarial_check.get("hierarchy_boundary_explicit"),
            False,
        )
        self.assertTrue(
            str(
                adversarial_check.get("strongest_adjacent_interpretation")
                or ""
            ).strip()
        )

        audit = browser._audit_fact_search_query(
            user_request,
            wrong_query,
            scope,
        )
        self.assertIsInstance(audit, dict)
        self.assertEqual(audit.get("decision"), "REWRITE")
        self.assertIs(audit.get("proposed_query_scope_match"), False)
        self.assertIs(audit.get("approved_query_scope_match"), True)
        self.assertTrue(str(audit.get("approved_search_query") or "").strip())
        certification = audit.get("certification") or {}
        self.assertIs(certification.get("accepted"), True)
        self.assertIs(
            certification.get("adjacent_interpretation_plausible"),
            False,
        )
        self.assertIs(
            certification.get("hierarchy_boundary_explicit"),
            True,
        )
        self.assertIs(certification.get("exact_entity_scope"), True)
        self.assertIs(certification.get("translation_boundary_clear"), True)
        self.assertIs(certification.get("standalone_for_search_engine"), True)

    def test_wrong_entity_missing_evidence_is_not_not_yet_available(self):
        from casper import browser

        audit = browser._audit_combined_fact_resolution(
            "SNH48现在有哪些正式分队？成员和剧场公演是怎么安排的？",
            "SNH48 internal official teams members theater performances 2026",
            {
                "scope_type": "CURRENT_ACTIVE_STATE",
                "requested_period": "current active state as of 2026-08-28",
                "allow_previous_period": False,
                "entity_scope": {
                    "target_entity": "SNH48",
                    "requested_relation": "internal official teams",
                    "required_facets": [
                        "team list",
                        "member assignment",
                        "theater performance organization",
                    ],
                    "included_scope": "SNH48 internal official teams",
                    "excluded_adjacent_scopes": [
                        "SNH48 GROUP affiliated or sister groups"
                    ],
                },
            },
            {
                "answer_status": "NOT_YET_AVAILABLE",
                "reason": "The supplied results do not contain a full list.",
            },
            [
                {
                    "title": "SNH48 GROUP affiliates",
                    "description": "Lists affiliated groups only.",
                    "domain": "example.test",
                    "url": "https://example.test/affiliates",
                    "page_success": True,
                    "page_error": "",
                    "page_content": "The page lists affiliated groups.",
                }
            ],
            [],
        )
        self.assertIsInstance(audit, dict)
        self.assertIs(audit.get("accepted"), False)
        self.assertIs(
            audit.get("not_missing_evidence_mislabeled_unavailable"),
            False,
        )

    def test_partial_fact_candidate_is_rejected(self):
        from casper import browser

        result = browser._validate_candidate_answer(
            "SNH48 current official teams, member assignment, and theater "
            "performance organization",
            {
                "title": "SNH48 official members and event page",
                "description": "Several members and one concert are shown.",
                "domain": "snh48.com",
                "url": "https://snh48.com/example",
                "page_content": (
                    "This page lists several members and an August 8 concert. "
                    "It does not provide the full current team structure, "
                    "member assignments, or theater performance organization."
                ),
            },
            "The source lists several members and one concert, but it does not "
            "provide the full official team list or theater schedule.",
        )
        self.assertIsInstance(result, dict)
        self.assertIs(result.get("accepted"), False)

    def test_placeholder_documentation_query_is_rejected(self):
        from casper import content_learning

        plan = {
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "target_app": "FM26",
            "content_kind": "tactics",
            "installation_queries": ["one complete documentation search"],
        }
        compliant, reason = content_learning._review_documentation_queries(
            "打开 FM26 战术文件夹", plan
        )
        self.assertIs(compliant, False)
        self.assertIn("Placeholder", reason)

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

    def test_external_fact_fallback_policy_contracts(self):
        from nerv import external_fact_fallback

        cases = (
            (
                "SNH48有哪些正式分队？",
                "LOW",
                "reviewable",
                False,
            ),
            (
                "李艺彤现在属于哪个团体？",
                "LOW",
                "changing",
                False,
            ),
            (
                "一份合同规定逾期付款每天收取未付款项5%的违约金，"
                "这条款需要注意什么？",
                "HIGH",
                None,
                False,
            ),
            (
                "袋熊的便便为什么是方形的？",
                "LOW",
                "stable",
                False,
            ),
            (
                "SNH48有哪些正式分队？成员现在如何分配，近期剧场公演如何安排？",
                "LOW",
                "changing",
                True,
            ),
        )
        for question, importance, knowledge_type, reusable_component in cases:
            with self.subTest(question=question):
                result = external_fact_fallback.assess_request(
                    question,
                    {"scope_type": "GENERAL_FACT"},
                )
                self.assertEqual(result.get("decision"), "ASK")
                self.assertEqual(result.get("importance"), importance)
                if knowledge_type is not None:
                    self.assertEqual(result.get("knowledge_type"), knowledge_type)
                if knowledge_type == "reviewable":
                    self.assertIsInstance(result.get("valid_for_days"), int)
                    self.assertLess(result.get("valid_for_days"), 3650)
                self.assertIs(
                    result.get("has_reusable_component"), reusable_component
                )

    def test_current_formal_unit_set_fallback_lifecycle_contract(self):
        from nerv import external_fact_fallback

        result = external_fact_fallback.assess_request(
            "SNH48目前有哪些正式Team？",
            {
                "scope_type": "CURRENT_ACTIVE_STATE",
                "requested_period": "current active state as of 2026-08-29",
                "allow_previous_period": False,
                "entity_scope": {
                    "target_entity": "SNH48",
                    "requested_relation": "current official team structure",
                    "required_facets": [
                        "list of official teams",
                        "current status of each team",
                    ],
                },
            },
        )
        self.assertEqual(result.get("decision"), "ASK")
        self.assertEqual(result.get("importance"), "LOW")
        self.assertEqual(
            result.get("lifecycle_basis"),
            "MAINTAINED_SET_OR_STRUCTURE",
        )
        self.assertIn(
            result.get("knowledge_type"),
            {"stable", "reviewable"},
        )
        if result.get("knowledge_type") == "stable":
            self.assertIsNone(result.get("valid_for_days"))
        else:
            self.assertIsInstance(result.get("valid_for_days"), int)
            self.assertLess(result.get("valid_for_days"), 3650)
        self.assertIs(result.get("has_reusable_component"), False)

    def test_historical_and_current_people_rosters_get_distinct_lifecycles(self):
        from nerv import external_fact_fallback

        historical_scope = {
            "scope_type": "EXPLICIT_PERIOD",
            "requested_period": "completed 2025 season",
            "allow_previous_period": False,
        }
        historical = external_fact_fallback.assess_request(
            "曼联2025赛季结束时的一线队阵容有哪些球员？",
            historical_scope,
        )
        current = external_fact_fallback.assess_request(
            "曼联目前的一线队阵容有哪些球员？",
            {
                "scope_type": "CURRENT_ACTIVE_STATE",
                "requested_period": "current active roster as of 2026-08-29",
                "allow_previous_period": False,
            },
        )

        self.assertEqual(historical.get("decision"), "ASK")
        self.assertEqual(historical.get("importance"), "LOW")
        self.assertEqual(historical.get("knowledge_type"), "stable")
        self.assertEqual(historical.get("lifecycle_basis"), "FIXED_HISTORY")
        self.assertEqual(historical.get("temporal_scope"), historical_scope)
        self.assertEqual(current.get("decision"), "ASK")
        self.assertEqual(current.get("importance"), "LOW")
        self.assertEqual(current.get("knowledge_type"), "changing")
        self.assertEqual(
            current.get("lifecycle_basis"),
            "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
        )
        self.assertIsNone(current.get("valid_for_days"))

    def test_external_answer_audit_scope_anchor_contract(self):
        from nerv import external_fact_fallback

        result = external_fact_fallback.audit_answer(
            "SNH48目前有哪些正式Team？",
            (
                "SNH48目前的正式Team为Team SII、Team NII、Team HII和"
                "Team X。这里列的是SNH48内部正式Team，不是成员名单或"
                "姐妹团名单。"
            ),
            {
                "results": [{
                    "title": "SNH48成员列表",
                    "domain": "zh.wikipedia.org",
                    "description": (
                        "该页面按Team SII、Team NII、Team HII和Team X"
                        "分类列出成员。"
                    ),
                    "page_content": "SNH48成员列表" * 5000,
                }],
            },
            {
                "decision": "ASK",
                "importance": "LOW",
                "sharing_risk": "NORMAL",
                "outbound_prompt": "SNH48目前有哪些正式Team？",
                "knowledge_type": "reviewable",
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "valid_for_days": 180,
                "has_reusable_component": False,
                "reason": "Formal team set is maintained structure.",
            },
        )
        self.assertEqual(result.get("decision"), "AUTO_VERIFY")
        self.assertIs(result.get("directly_answers"), True)
        self.assertIs(result.get("complete_for_request"), True)
        self.assertIs(result.get("policy_satisfied"), True)
        self.assertIs(result.get("no_evidence_conflict"), True)
        self.assertIn(
            result.get("answer_disposition"),
            {"USE_AS_IS", "USE_CANONICAL_CORE"},
        )
        if result.get("answer_disposition") == "USE_CANONICAL_CORE":
            self.assertTrue(
                str(result.get("canonical_answer") or "").strip()
            )

    def test_external_answer_audit_cleans_complete_core_contract(self):
        from nerv import external_fact_fallback

        current_date = external_fact_fallback._authoritative_local_date()
        result = external_fact_fallback.audit_answer(
            "SNH48目前有哪些正式Team？",
            (
                "截至" + current_date + "，SNH48目前有四个正式Team："
                "Team SII、Team NII、Team HII和Team X。"
                "一场不存在的2026 Youth Gala也证明了这份名单。"
            ),
            {"results": []},
            {
                "decision": "ASK",
                "importance": "LOW",
                "sharing_risk": "NORMAL",
                "outbound_prompt": "SNH48目前有哪些正式Team？",
                "knowledge_type": "reviewable",
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "valid_for_days": 180,
                "has_reusable_component": False,
                "reason": "Formal team set is maintained structure.",
            },
        )
        self.assertEqual(result.get("decision"), "AUTO_VERIFY")
        self.assertEqual(
            result.get("answer_disposition"), "USE_CANONICAL_CORE"
        )
        self.assertIs(result.get("candidate_has_removable_additions"), True)
        clean = str(result.get("canonical_answer") or "")
        for team in ("Team SII", "Team NII", "Team HII", "Team X"):
            self.assertIn(team, clean)
        self.assertNotIn("Youth Gala", clean)

    def test_mixed_claim_lifecycle_audit_contract(self):
        from nerv import external_fact_fallback

        def claim(subject, text):
            return {
                "persist": True,
                "directly_supported_by_answer": True,
                "no_evidence_conflict": True,
                "subject": subject,
                "claim": text,
                "knowledge_type": "stable",
                "valid_for_days": None,
                "confidence": 0.95,
                "topics": ["contract test"],
                "knowledge_domain": "culture_entertainment",
                "cluster_label": "contract_test",
                "reason": "First partition proposal.",
            }

        result = external_fact_fallback.audit_partition_lifecycles(
            "请回答组织结构、长期概念与某人的当前归属。",
            "完整外部回答。",
            {"results": []},
            {
                "decision": "ASK",
                "importance": "LOW",
                "sharing_risk": "NORMAL",
                "knowledge_type": "changing",
                "has_reusable_component": True,
            },
            {
                "answer_usable": True,
                "directly_answers": True,
                "complete_for_request": True,
                "claims": [
                    claim(
                        "SNH48当前正式Team",
                        "SNH48目前共有四支正式Team：SII、NII、HII和X。",
                    ),
                    claim(
                        "期生与Team的概念区别",
                        "期生表示加入批次，Team表示正式演出单位。",
                    ),
                    claim(
                        "某人当前团体归属",
                        "某人目前属于一个指定团体。",
                    ),
                ],
                "reason": "Synthetic mixed lifecycle contract.",
            },
        )
        self.assertEqual(result.get("lifecycle_audit_status"), "PASSED")
        claims = result.get("claims") or []
        self.assertEqual(len(claims), 3)
        self.assertIn(
            claims[0].get("knowledge_type"),
            {"stable", "reviewable"},
        )
        self.assertEqual(
            claims[0].get("lifecycle_basis"),
            "MAINTAINED_SET_OR_STRUCTURE",
        )
        self.assertIs(claims[0].get("persist"), True)
        if claims[0].get("knowledge_type") == "stable":
            self.assertIsNone(claims[0].get("valid_for_days"))
        else:
            self.assertIsInstance(claims[0].get("valid_for_days"), int)
            self.assertLess(claims[0].get("valid_for_days"), 3650)
        self.assertEqual(claims[1].get("knowledge_type"), "stable")
        self.assertEqual(
            claims[1].get("lifecycle_basis"),
            "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM",
        )
        self.assertIs(claims[1].get("persist"), True)
        self.assertIsNone(claims[1].get("valid_for_days"))
        self.assertIn(
            claims[2].get("knowledge_type"),
            {"changing", "event", "news"},
        )
        self.assertEqual(
            claims[2].get("lifecycle_basis"),
            "TRANSIENT_CURRENT_STATE_OR_EVENT",
        )
        self.assertIs(claims[2].get("persist"), False)

    def test_audited_fact_lookup_historical_snapshot_partition_contract(self):
        from nerv import external_fact_fallback

        exact_period = "2025 (specifically updated as of November 2025)"
        answer = (
            "截至2025年11月，示例联队一线队成员为球员甲、球员乙和球员丙。"
        )
        result = external_fact_fallback.partition_mixed_answer(
            "2025年示例联队的一线队阵容有哪些球员？",
            answer,
            {
                "results": [{
                    "title": "示例联队2025年11月阵容存档",
                    "url": "https://example.test/roster-2025-11",
                    "domain": "example.test",
                    "snippet": answer,
                    "source_score": 95,
                }],
            },
            {
                "decision": "ASK",
                "importance": "LOW",
                "sharing_risk": "NORMAL",
                "knowledge_type": "changing",
                "lifecycle_basis": "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
                "valid_for_days": None,
                "has_reusable_component": True,
                "reason": "The answer was already accepted for this turn.",
            },
            prompt_path="prompts/nerv_fact_lookup_knowledge_partition.txt",
            answer_source="casper_audited_fact_lookup",
            additional_context={
                "authoritative_current_date": (
                    external_fact_fallback._authoritative_local_date()
                ),
                "current_date_role": "HOST_LOCAL_TEMPORAL_AUTHORITY",
                "accepted_answer_records": [{
                    "answer": answer,
                    "answer_status": "ACCEPTED",
                    "temporal_validation": {
                        "time_scope_match": True,
                        "source_period": exact_period,
                    },
                }],
                "source_supported_periods": [exact_period],
                "strict_source_temporal_scope": True,
                "answer_already_accepted_for_current_turn": True,
                "knowledge_capture_cannot_change_user_reply": True,
            },
        )

        self.assertIsInstance(result, dict)
        self.assertIs(result.get("answer_usable"), True)
        self.assertEqual(result.get("lifecycle_audit_status"), "PASSED")
        reusable = [
            claim for claim in result.get("claims") or []
            if claim.get("persist") is True
        ]
        self.assertEqual(len(reusable), 1)
        claim = reusable[0]
        self.assertEqual(claim.get("lifecycle_basis"), "FIXED_HISTORY")
        self.assertEqual(claim.get("knowledge_type"), "stable")
        self.assertIsNone(claim.get("valid_for_days"))
        self.assertEqual(
            (claim.get("temporal_scope") or {}).get("requested_period"),
            exact_period,
        )
        self.assertIs(
            (claim.get("temporal_scope") or {}).get(
                "allow_previous_period"
            ),
            False,
        )
        self.assertIn("2025", str(claim.get("claim") or ""))

    def test_formal_unit_set_survives_mixed_answer_partition_contract(self):
        from nerv import external_fact_fallback

        question = (
            "SNH48目前有哪些正式Team？‘期生’表示什么，它与Team归属是什么"
            "关系？李艺彤目前是否仍是SNH48现役成员？"
        )
        answer = (
            "截至2026年8月，SNH48上海本部的正式Team为Team SII、Team NII、"
            "Team HII和Team X。‘期生’表示成员加入团体的招募批次，是历史"
            "属性；Team表示组织和公演归属，两者可以同时存在。李艺彤于2019"
            "年毕业，目前不是SNH48现役成员，也不属于任何现役Team。"
        )
        result = external_fact_fallback.partition_mixed_answer(
            question,
            answer,
            {"results": []},
            {
                "decision": "ASK",
                "importance": "LOW",
                "sharing_risk": "NORMAL",
                "knowledge_type": "changing",
                "valid_for_days": None,
                "has_reusable_component": True,
            },
        )
        self.assertIsInstance(result, dict)
        self.assertIs(result.get("answer_usable"), True)
        self.assertEqual(result.get("lifecycle_audit_status"), "PASSED")
        claims = result.get("claims") or []
        formal_units = [
            claim for claim in claims
            if all(
                name in str(claim.get("claim") or "")
                for name in ("Team SII", "Team NII", "Team HII", "Team X")
            )
        ]
        self.assertEqual(len(formal_units), 1)
        self.assertIs(formal_units[0].get("persist"), True)
        self.assertEqual(
            formal_units[0].get("lifecycle_basis"),
            "MAINTAINED_SET_OR_STRUCTURE",
        )
        self.assertIn(
            formal_units[0].get("knowledge_type"),
            {"stable", "reviewable"},
        )
        definitions = [
            claim for claim in claims
            if "期生" in str(claim.get("claim") or "")
            and "批次" in str(claim.get("claim") or "")
        ]
        self.assertTrue(any(claim.get("persist") is True for claim in definitions))
        current_status = [
            claim for claim in claims
            if "李艺彤" in str(claim.get("claim") or "")
            and any(
                marker in str(claim.get("claim") or "")
                for marker in ("目前", "现役", "现在")
            )
        ]
        self.assertTrue(current_status)
        self.assertTrue(all(claim.get("persist") is False for claim in current_status))

    def test_curator_entity_hierarchy_and_relation_contract(self):
        import tools
        from nerv.knowledge_curator import KnowledgeCurator

        knowledge_ids = ["curator_contract_0", "curator_contract_1"]
        catalog = [{
            "topic_id": "snh48-ecosystem",
            "title": "SNH48 ecosystem",
            "aliases": ["SNH48", "SNH48 GROUP"],
            "keywords": ["idol organization"],
            "entities": [
                {
                    "id": "snh48_group",
                    "name": "SNH48 GROUP",
                    "type": "umbrella_organization",
                    "aliases": [],
                },
                {
                    "id": "snh48",
                    "name": "SNH48",
                    "type": "idol_group",
                    "aliases": [],
                },
                {
                    "id": "team_sii",
                    "name": "Team SII",
                    "type": "internal_team",
                    "aliases": [],
                },
            ],
            "claims": [],
        }]
        packet = {
            "local_date": "2026-08-29",
            "already_verified_items": [
                {
                    "knowledge_id": knowledge_ids[0],
                    "subject": "SNH48的期生概念",
                    "claim": "SNH48采用“期生”表示成员加入该团体的批次。",
                    "topics": ["SNH48"],
                    "knowledge_domain": "culture_entertainment",
                    "cluster_label": "SNH48",
                    "knowledge_type": "stable",
                    "expires_at": None,
                    "status": "verified",
                    "verification_status": "contract_test",
                    "verification_level": "contract_test",
                    "provenance": {},
                },
                {
                    "knowledge_id": knowledge_ids[1],
                    "subject": "Team SII与SNH48的关系",
                    "claim": "Team SII是SNH48内部的正式Team，不是其姐妹团体。",
                    "topics": ["SNH48", "Team SII"],
                    "knowledge_domain": "culture_entertainment",
                    "cluster_label": "SNH48",
                    "knowledge_type": "stable",
                    "expires_at": None,
                    "status": "verified",
                    "verification_status": "contract_test",
                    "verification_level": "contract_test",
                    "provenance": {},
                },
            ],
            "existing_topic_ecosystems": catalog,
            "immutable_rules": {
                "verification_may_not_be_changed": True,
                "changing_event_news_are_not_in_this_queue": True,
                "one_topic_document_is_a_broad_knowledge_ecosystem": True,
                "topic_co_location_never_merges_distinct_entities": True,
                "internal_units_are_not_sister_organizations_of_their_parent": True,
            },
        }
        raw = tools.run_ai_prompt(
            "prompts/nerv_daily_knowledge_curator.txt",
            json.dumps(packet, ensure_ascii=False),
            expect_json=True,
            num_ctx=8192,
            num_predict=1800,
            think=False,
            model_name="gemma4:12b",
            json_schema=KnowledgeCurator._schema_for(knowledge_ids),
        )
        assignments, errors = KnowledgeCurator._validate_plan(
            raw,
            knowledge_ids,
            catalog,
        )
        self.assertIsNotNone(assignments, errors)
        by_id = {item["knowledge_id"]: item for item in assignments}
        generation = by_id[knowledge_ids[0]]
        self.assertEqual(generation.get("decision"), "STORE")
        self.assertEqual(
            (generation.get("subject_entity") or {}).get("id"),
            "snh48",
        )
        self.assertEqual(
            generation.get("selected_subject_entity_id"),
            "snh48",
        )
        self.assertIn("SNH48", generation.get("literal_claim_subject") or "")
        relation = by_id[knowledge_ids[1]]
        self.assertEqual(relation.get("decision"), "STORE")
        self.assertIs(relation.get("entity_scope_preserved"), True)
        self.assertIs(
            relation.get("relationship_semantics_consistent"),
            True,
        )
        relation_words = " ".join(
            str(item.get("relation") or "")
            for item in relation.get("related_entities") or []
        ).casefold()
        self.assertNotIn("sister", relation_words)
        related_by_id = {
            str(item.get("id") or ""): item
            for item in relation.get("related_entities") or []
            if isinstance(item, dict)
        }
        self.assertIn("snh48", related_by_id)
        self.assertTrue(
            str(
                related_by_id["snh48"].get("claim_relation_evidence") or ""
            ).strip()
        )

    def test_query_translation_and_focused_follow_up_contract(self):
        from casper import browser

        user_request = (
            "SNH48目前有哪些正式Team？“期生”和正式Team在组织上有什么区别？"
            "李艺彤现在属于哪个团体？"
        )
        wrong_query = (
            "SNH48 official teams list and difference between trainee (期生) "
            "and official team members, Li Yitong current group status"
        )
        entity_scope = browser._plan_fact_entity_scope(
            user_request,
            wrong_query,
        )
        self.assertIsInstance(entity_scope, dict)
        boundaries = entity_scope.get("source_language_boundaries") or []
        open_boundary = next(
            (
                item for item in boundaries
                if isinstance(item, dict)
                and "期生" in str(item.get("source_expression") or "")
            ),
            None,
        )
        self.assertIsInstance(open_boundary, dict)
        self.assertEqual(
            open_boundary.get("meaning_status"),
            "OPEN_RESEARCH_TARGET",
        )
        self.assertEqual(
            open_boundary.get("translation_policy"),
            "PRESERVE_SOURCE_EXPRESSION",
        )
        self.assertIsNone(open_boundary.get("established_equivalent"))
        repaired = browser._audit_fact_search_query(
            user_request,
            wrong_query,
            entity_scope,
        )
        self.assertIsInstance(repaired, dict)
        approved_query = str(repaired.get("approved_search_query") or "")
        self.assertIn("期生", approved_query)
        self.assertNotIn("trainee", approved_query.casefold())
        self.assertIs(
            (repaired.get("certification") or {}).get("accepted"),
            True,
        )

        focused_query = "SNH48 期生 加入批次 官方成员资料"
        sibling_query = "SNH48 内部正式Team 李艺彤当前团体归属 官方"
        gap_plan = {
            "action": "RESEARCH_AGAIN",
            "gap_type": "期生定义与当前归属两个证据缺口",
            "follow_up_queries": [focused_query, sibling_query],
            "reason": "Each query investigates one missing facet.",
        }
        focused = browser._audit_fact_search_query(
            user_request,
            focused_query,
            entity_scope,
            query_role="FOCUSED_FOLLOW_UP",
            query_set=[focused_query, sibling_query],
            gap_plan=gap_plan,
        )
        self.assertIsInstance(focused, dict)
        self.assertIn("期生", focused.get("approved_search_query") or "")
        self.assertIs(
            (focused.get("certification") or {}).get("accepted"),
            True,
        )
        self.assertIs(
            (focused.get("certification") or {}).get(
                "focused_facet_preserved"
            ),
            True,
        )

    def test_knowledge_correction_authority_contract(self):
        import tools
        from nerv import objective_fact

        public = objective_fact.audit_knowledge_correction(
            tools.run_ai_prompt,
            tools.unload_model,
            "不对，你刚才给出的正式Team名单有误，请重新核实。",
            "Assistant: 该组织目前设有甲、乙、丙、丁四个正式Team。",
            [{
                "id": "knowledge-public-units",
                "subject": "某组织当前正式Team",
                "claim": "该组织目前设有甲、乙、丙、丁四个正式Team。",
                "knowledge_type": "reviewable",
                "status": "verified",
            }],
        )
        self.assertEqual(public.get("decision"), "OBJECTIVE_DISPUTE")
        self.assertEqual(
            public.get("disputed_knowledge_ids"),
            ["knowledge-public-units"],
        )
        self.assertTrue(str(public.get("claim_to_verify") or "").strip())

        personal = objective_fact.audit_knowledge_correction(
            tools.run_ai_prompt,
            tools.unload_model,
            "不对，我自己的电脑是另一个型号。",
            "Assistant: 你的电脑是示例型号。",
            [],
        )
        self.assertEqual(personal.get("decision"), "PERSONAL_AUTHORITY")
        self.assertEqual(personal.get("disputed_knowledge_ids"), [])


if __name__ == "__main__":
    unittest.main()
