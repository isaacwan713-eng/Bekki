import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta, timezone

import knowledge
from casper import browser
from nerv import external_fact_fallback


class ExternalFactFallbackPolicyTests(unittest.TestCase):
    def _assessment(self, **updates):
        value = {
            "decision": "ASK",
            "importance": "LOW",
            "sharing_risk": "NORMAL",
            "outbound_prompt": "SNH48有哪些正式分队？",
            "knowledge_type": "reviewable",
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "valid_for_days": 90,
            "has_reusable_component": False,
            "reason": "low-impact structural knowledge",
        }
        value.update(updates)
        if "lifecycle_basis" not in updates:
            if value["knowledge_type"] in {"changing", "event", "news"}:
                value["lifecycle_basis"] = (
                    "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT"
                )
            elif value["knowledge_type"] == "reviewable":
                value["lifecycle_basis"] = "MAINTAINED_SET_OR_STRUCTURE"
        return value

    def _policy_audit(self, **updates):
        value = {
            "decision": "ASK",
            "importance": "LOW",
            "sharing_risk": "NORMAL",
            "outbound_prompt": "SNH48有哪些正式分队？",
            "knowledge_type": "reviewable",
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "valid_for_days": 90,
            "has_reusable_component": False,
            "entity_scope_preserved": True,
            "lifecycle_proportional": True,
            "review_interval_proportional": True,
            "reason": "Independent lifecycle and freshness audit passed.",
        }
        value.update(updates)
        if "lifecycle_basis" not in updates:
            if value["knowledge_type"] in {"changing", "event", "news"}:
                value["lifecycle_basis"] = (
                    "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT"
                )
            elif value["knowledge_type"] == "reviewable":
                value["lifecycle_basis"] = "MAINTAINED_SET_OR_STRUCTURE"
        return value

    def _audit(self, **updates):
        value = {
            "decision": "AUTO_VERIFY",
            "answer_disposition": "USE_AS_IS",
            "directly_answers": True,
            "complete_for_request": True,
            "policy_satisfied": True,
            "no_evidence_conflict": True,
            "candidate_has_removable_additions": False,
            "confidence": 0.92,
            "subject": "SNH48正式分队",
            "canonical_answer": (
                "SNH48的正式分队为Team SII、NII、HII和X。"
            ),
            "canonical_claim": "SNH48的正式分队为Team SII、NII、HII和X。",
            "topics": ["SNH48", "分队"],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "SNH48",
            "reason": "Complete low-impact answer.",
        }
        value.update(updates)
        if "canonical_claim" in updates and "canonical_answer" not in updates:
            value["canonical_answer"] = str(updates["canonical_claim"])
        return value

    def test_audited_fact_lookup_intake_persists_exact_historical_snapshot(self):
        partition = {
            "answer_usable": True,
            "directly_answers": True,
            "complete_for_request": True,
            "claims": [{
                "persist": True,
                "directly_supported_by_answer": True,
                "no_evidence_conflict": True,
                "subject": "SNH48 Team SII 2025年11月成员快照",
                "claim": "截至2025年11月，Team SII成员包括示例成员甲和乙。",
                "knowledge_type": "stable",
                "lifecycle_basis": "FIXED_HISTORY",
                "valid_for_days": None,
                "confidence": 0.93,
                "topics": ["SNH48", "Team SII"],
                "knowledge_domain": "culture_entertainment",
                "cluster_label": "SNH48",
                "temporal_scope": {
                    "scope_type": "EXPLICIT_PERIOD",
                    "requested_period": "2025 (specifically updated as of November 2025)",
                    "allow_previous_period": False,
                },
                "reason": "Exact completed source-supported snapshot.",
                "lifecycle_audit_status": "PASSED",
                "partition_lifecycle_audit_version": 10,
            }],
            "reason": "Historical snapshot can be reused with exact identity.",
        }
        search_result = {
            "status": "OK",
            "direct_reply": "截至2025年11月，Team SII成员包括示例成员甲和乙。",
            "answers": [{
                "accepted": True,
                "answer": "截至2025年11月，Team SII成员包括示例成员甲和乙。",
                "answer_status": "ACCEPTED",
                "temporal_validation": {
                    "time_scope_match": True,
                    "source_period": (
                        "2025 (specifically updated as of November 2025)"
                    ),
                },
            }],
            "results": [{
                "title": "Official roster archive",
                "url": "https://example.test/roster-2025-11",
                "domain": "example.test",
            }],
        }
        with patch.object(
            external_fact_fallback,
            "partition_mixed_answer",
            return_value=partition,
        ) as partition_call, patch.object(
            knowledge,
            "apply_verified_fact_lookup_partitioned_claim",
            return_value=("verified", {"id": "knowledge-snapshot"}),
        ) as persist:
            result = external_fact_fallback.intake_audited_fact_lookup(
                "2025年SNH48 Team SII有哪些成员？",
                search_result["direct_reply"],
                search_result,
            )

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["knowledge_ids"], ["knowledge-snapshot"])
        context = partition_call.call_args.kwargs["additional_context"]
        self.assertEqual(
            context["source_supported_periods"],
            ["2025 (specifically updated as of November 2025)"],
        )
        self.assertIs(context["strict_source_temporal_scope"], True)
        persist.assert_called_once()

    def test_audited_fact_lookup_intake_does_not_store_current_people_roster(self):
        partition = {
            "answer_usable": True,
            "directly_answers": True,
            "complete_for_request": True,
            "claims": [{
                "persist": False,
                "directly_supported_by_answer": True,
                "no_evidence_conflict": True,
                "subject": "示例球队当前阵容",
                "claim": "示例球队当前阵容包括球员甲和乙。",
                "knowledge_type": "changing",
                "lifecycle_basis": "TRANSIENT_CURRENT_STATE_OR_EVENT",
                "valid_for_days": None,
                "confidence": 0.94,
                "topics": ["示例球队"],
                "knowledge_domain": "sports",
                "cluster_label": "示例球队",
                "temporal_scope": None,
                "reason": "A live people roster is current-turn only.",
                "lifecycle_audit_status": "PASSED",
                "partition_lifecycle_audit_version": 10,
            }],
            "reason": "No reusable claim.",
        }
        search_result = {
            "direct_reply": "示例球队当前阵容包括球员甲和乙。",
            "answers": [{
                "accepted": True,
                "answer": "示例球队当前阵容包括球员甲和乙。",
                "temporal_validation": {
                    "time_scope_match": True,
                    "source_period": "current active state as of 2026-08-30",
                },
            }],
        }
        with patch.object(
            external_fact_fallback,
            "partition_mixed_answer",
            return_value=partition,
        ), patch.object(
            knowledge,
            "apply_verified_fact_lookup_partitioned_claim",
        ) as persist:
            result = external_fact_fallback.intake_audited_fact_lookup(
                "示例球队目前有哪些球员？",
                search_result["direct_reply"],
                search_result,
            )

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["knowledge_ids"], [])
        persist.assert_not_called()

    def test_fact_lookup_partition_schema_locks_exact_source_period(self):
        captured = {}

        def model_call(_prompt, _payload, **kwargs):
            captured["schema"] = kwargs["json_schema"]
            return {
                "answer_usable": True,
                "directly_answers": True,
                "complete_for_request": True,
                "claims": [],
                "reason": "No reusable claims in schema inspection.",
            }

        with patch("tools.run_ai_prompt", side_effect=model_call), patch(
            "tools.unload_model"
        ), patch.object(
            external_fact_fallback,
            "audit_partition_lifecycles",
            side_effect=lambda _u, _a, _s, _p, value, **_kwargs: value,
        ):
            external_fact_fallback.partition_mixed_answer(
                "2025年示例球队有哪些球员？",
                "截至2025年11月的成员快照。",
                {"results": []},
                self._assessment(has_reusable_component=True),
                additional_context={
                    "strict_source_temporal_scope": True,
                    "source_supported_periods": [
                        "2025 (specifically updated as of November 2025)"
                    ],
                },
            )

        temporal = captured["schema"]["properties"]["claims"]["items"][
            "properties"
        ]["temporal_scope"]
        self.assertEqual(
            temporal["anyOf"][0]["properties"]["requested_period"]["enum"],
            ["2025 (specifically updated as of November 2025)"],
        )

    def test_fact_lookup_partition_schema_forbids_unsourced_snapshot_period(self):
        captured = {}

        def model_call(_prompt, _payload, **kwargs):
            captured["schema"] = kwargs["json_schema"]
            return {
                "answer_usable": True,
                "directly_answers": True,
                "complete_for_request": True,
                "claims": [],
                "reason": "No source-supported snapshot period.",
            }

        with patch("tools.run_ai_prompt", side_effect=model_call), patch(
            "tools.unload_model"
        ), patch.object(
            external_fact_fallback,
            "audit_partition_lifecycles",
            side_effect=lambda _u, _a, _s, _p, value, **_kwargs: value,
        ):
            external_fact_fallback.partition_mixed_answer(
                "2025年示例球队有哪些球员？",
                "一个没有精确时间边界的名单。",
                {"results": []},
                self._assessment(has_reusable_component=True),
                additional_context={
                    "strict_source_temporal_scope": True,
                    "source_supported_periods": [],
                },
            )

        temporal = captured["schema"]["properties"]["claims"]["items"][
            "properties"
        ]["temporal_scope"]
        self.assertEqual(temporal, {"type": "null"})

    def test_preflight_preserves_reviewable_structural_knowledge(self):
        result = self._assessment()
        with patch(
            "tools.run_ai_prompt",
            side_effect=[result, self._policy_audit()],
        ), patch(
            "tools.unload_model"
        ):
            decision = external_fact_fallback.assess_request(
                "SNH48有哪些正式分队？",
                {"scope_type": "CURRENT_ACTIVE_STATE"},
            )
        self.assertEqual(decision["decision"], "ASK")
        self.assertEqual(decision["knowledge_type"], "reviewable")
        self.assertEqual(
            decision["lifecycle_basis"],
            "MAINTAINED_SET_OR_STRUCTURE",
        )
        self.assertEqual(decision["valid_for_days"], 90)

    def test_current_formal_unit_set_uses_maintained_structure_basis(self):
        first = self._assessment(
            outbound_prompt="某组织目前有哪些正式部门？",
            valid_for_days=180,
        )
        audited = self._policy_audit(
            outbound_prompt="某组织目前有哪些正式部门？",
            valid_for_days=180,
        )
        with patch(
            "tools.run_ai_prompt", side_effect=[first, audited]
        ), patch("tools.unload_model"):
            decision = external_fact_fallback.assess_request(
                "某组织目前有哪些正式部门？",
                {
                    "scope_type": "CURRENT_ACTIVE_STATE",
                    "required_facets": [
                        "list of formal departments",
                        "current status of each department",
                    ],
                },
            )
        self.assertEqual(decision["decision"], "ASK")
        self.assertEqual(decision["knowledge_type"], "reviewable")
        self.assertEqual(
            decision["lifecycle_basis"],
            "MAINTAINED_SET_OR_STRUCTURE",
        )
        self.assertEqual(decision["valid_for_days"], 180)

    def test_completed_historical_roster_uses_fixed_history_scope(self):
        first = self._assessment(
            outbound_prompt="曼联2025赛季结束时的一线队阵容有哪些球员？",
            knowledge_type="stable",
            lifecycle_basis="FIXED_HISTORY",
            valid_for_days=None,
        )
        audited = self._policy_audit(
            outbound_prompt="曼联2025赛季结束时的一线队阵容有哪些球员？",
            knowledge_type="stable",
            lifecycle_basis="FIXED_HISTORY",
            valid_for_days=None,
        )
        scope = {
            "scope_type": "EXPLICIT_PERIOD",
            "requested_period": "completed 2025 season",
            "allow_previous_period": False,
        }
        with patch(
            "tools.run_ai_prompt", side_effect=[first, audited]
        ), patch("tools.unload_model"):
            decision = external_fact_fallback.assess_request(
                "曼联2025赛季结束时的一线队阵容有哪些球员？",
                scope,
            )

        self.assertEqual(decision["decision"], "ASK")
        self.assertEqual(decision["knowledge_type"], "stable")
        self.assertEqual(decision["lifecycle_basis"], "FIXED_HISTORY")
        self.assertEqual(decision["temporal_scope"], scope)

    def test_current_people_roster_remains_transient_and_current_only(self):
        first = self._assessment(
            outbound_prompt="曼联目前的一线队阵容有哪些球员？",
            knowledge_type="changing",
            lifecycle_basis="TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
            valid_for_days=None,
        )
        audited = self._policy_audit(
            outbound_prompt="曼联目前的一线队阵容有哪些球员？",
            knowledge_type="changing",
            lifecycle_basis="TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
            valid_for_days=None,
        )
        with patch(
            "tools.run_ai_prompt", side_effect=[first, audited]
        ), patch("tools.unload_model"):
            decision = external_fact_fallback.assess_request(
                "曼联目前的一线队阵容有哪些球员？",
                {
                    "scope_type": "CURRENT_ACTIVE_STATE",
                    "requested_period": "current active roster",
                    "allow_previous_period": False,
                },
            )

        self.assertEqual(decision["decision"], "ASK")
        self.assertEqual(decision["knowledge_type"], "changing")
        self.assertEqual(
            decision["lifecycle_basis"],
            "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
        )
        self.assertIsNone(decision["valid_for_days"])

    def test_preflight_receives_only_authoritative_request_and_time_scope(self):
        first = self._assessment(valid_for_days=180)
        audited = self._policy_audit(valid_for_days=180)
        with patch(
            "tools.run_ai_prompt", side_effect=[first, audited]
        ) as model, patch("tools.unload_model"):
            external_fact_fallback.assess_request(
                "某组织目前有哪些正式部门？",
                {
                    "scope_type": "CURRENT_ACTIVE_STATE",
                    "requested_period": "current active state",
                    "allow_previous_period": False,
                    "entity_scope": {
                        "required_facets": [
                            "list of formal departments",
                            "current status of each department",
                        ],
                    },
                },
            )
        first_packet = json.loads(model.call_args_list[0].args[1])
        self.assertEqual(
            first_packet["authoritative_public_fact_request"],
            "某组织目前有哪些正式部门？",
        )
        self.assertEqual(
            first_packet["retrieval_time_scope"]["scope_type"],
            "CURRENT_ACTIVE_STATE",
        )
        self.assertIs(
            first_packet["retrieval_scope_is_non_authoritative"], True
        )
        self.assertNotIn("fact_scope", first_packet)
        self.assertNotIn("entity_scope", first_packet)
        self.assertNotIn(
            "current status of each department",
            json.dumps(first_packet, ensure_ascii=False),
        )

    def test_policy_audit_is_not_anchored_to_first_lifecycle(self):
        first = self._assessment(
            knowledge_type="changing",
            valid_for_days=None,
        )
        audited = self._policy_audit(valid_for_days=180)
        with patch(
            "tools.run_ai_prompt", side_effect=[first, audited]
        ) as model, patch("tools.unload_model"):
            decision = external_fact_fallback.assess_request(
                "某组织目前有哪些正式部门？",
                {"scope_type": "CURRENT_ACTIVE_STATE"},
            )
        audit_packet = json.loads(model.call_args_list[1].args[1])
        self.assertNotIn("first_governor_policy", audit_packet)
        preview = audit_packet["first_governor_sharing_preview"]
        self.assertEqual(
            set(preview),
            {"decision", "importance", "sharing_risk", "outbound_prompt"},
        )
        for field in (
            "knowledge_type",
            "lifecycle_basis",
            "valid_for_days",
            "has_reusable_component",
            "reason",
        ):
            self.assertNotIn(field, preview)
        self.assertEqual(
            decision["lifecycle_basis"],
            "MAINTAINED_SET_OR_STRUCTURE",
        )

    def test_standalone_transient_basis_is_explicitly_nonstructural(self):
        self.assertTrue(
            external_fact_fallback._fallback_lifecycle_shape_valid(
                "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
                "changing",
                None,
            )
        )
        self.assertFalse(
            external_fact_fallback._fallback_lifecycle_shape_valid(
                "TRANSIENT_CURRENT_STATE_OR_EVENT",
                "changing",
                None,
            )
        )

    def test_answer_audit_keeps_noisy_web_context_bounded_and_subordinate(self):
        noisy_results = []
        for index in range(16):
            noisy_results.append({
                "title": "SNH48成员列表" + str(index),
                "domain": "example.org",
                "description": "成员名单页面" * 800,
                "page_content": "相邻页面正文" * 4000,
            })
        candidate = (
            "SNH48目前的正式Team为Team SII、Team NII、Team HII和Team X。"
            * 500
        )
        certification_context = {
            "performed": True,
            "provider": "ChatGPT Desktop",
            "initial_answer": "不应进入审计包" * 1000,
            "certification_prompt": "不应进入审计包" * 1000,
        }
        with patch(
            "tools.run_ai_prompt", return_value=self._audit()
        ) as model, patch("tools.unload_model"), patch.object(
            external_fact_fallback,
            "_authoritative_local_date",
            return_value="2026-08-29",
        ):
            result = external_fact_fallback.audit_answer(
                "SNH48目前有哪些正式Team？",
                candidate,
                {"results": noisy_results},
                self._assessment(valid_for_days=180),
                certification_context=certification_context,
            )
        self.assertEqual(result["decision"], "AUTO_VERIFY")
        payload_text = model.call_args.args[1]
        self.assertLess(len(payload_text.encode("utf-8")), 24000)
        packet = json.loads(payload_text)
        self.assertEqual(
            list(packet)[-1],
            "final_scope_anchor",
        )
        self.assertEqual(
            packet["authoritative_user_request"],
            "SNH48目前有哪些正式Team？",
        )
        self.assertEqual(
            packet["authoritative_runtime_context"]["current_date"],
            "2026-08-29",
        )
        self.assertEqual(
            packet["authoritative_runtime_context"]["date_role"],
            "AUTHORITATIVE_FOR_TEMPORAL_JUDGMENTS",
        )
        self.assertEqual(
            packet["audit_evidence_contract"][
                "latent_model_knowledge_role"
            ],
            "NOT_EVIDENCE",
        )
        self.assertEqual(
            packet["audit_evidence_contract"][
                "missing_web_corroboration_role"
            ],
            "EXPECTED_AFTER_BOUNDED_RESEARCH_NOT_A_CONFLICT",
        )
        self.assertEqual(
            packet["final_scope_anchor"]["authoritative_user_request"],
            "SNH48目前有哪些正式Team？",
        )
        self.assertEqual(
            packet["final_scope_anchor"]["authoritative_current_date"],
            "2026-08-29",
        )
        self.assertEqual(
            packet["final_scope_anchor"]["latent_model_knowledge_role"],
            "NOT_EVIDENCE",
        )
        self.assertEqual(packet["web_evidence_role"], "CONFLICT_CHECK_ONLY")
        evidence = packet["bounded_web_conflict_evidence"]
        self.assertEqual(len(evidence), 6)
        self.assertTrue(all("page_content" not in item for item in evidence))
        self.assertTrue(all("description" not in item for item in evidence))
        self.assertNotIn("bounded_web_evidence", packet)
        self.assertEqual(
            packet["certification_summary"],
            {"performed": True, "provider": "ChatGPT Desktop"},
        )
        self.assertNotIn("initial_answer", packet["certification_summary"])
        self.assertNotIn(
            "certification_prompt", packet["certification_summary"]
        )

    def test_answer_audit_prompt_forbids_evidence_scope_substitution(self):
        prompt = Path(
            "prompts/external_fact_fallback_audit.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("binding audit pair", prompt)
        self.assertIn("final_scope_anchor", prompt)
        self.assertIn("cannot redefine", prompt)
        self.assertIn("conflict-check-only", prompt)
        self.assertIn("authoritative_runtime_context.current_date", prompt)
        self.assertIn("Do not output a final decision", prompt)
        self.assertIn("states deterministically from your semantic findings", prompt)
        self.assertIn("Do not add a correction", prompt)
        self.assertIn("NOT evidence", prompt)
        self.assertIn("Candidate credibility is not global", prompt)
        self.assertIn("absence of independent web corroboration", prompt)
        self.assertIn("must not be reduced", prompt)
        self.assertIn("Mandatory core-retention rule", prompt)
        self.assertIn("This is not discretionary", prompt)
        self.assertIn("formal units an organization has", prompt)
        self.assertIn("NO_COMPLETE_CORE", prompt)

    def test_answer_audit_schema_exposes_findings_not_global_verdict(self):
        schema = external_fact_fallback.FACT_FALLBACK_AUDIT_SCHEMA
        properties = schema["properties"]
        self.assertNotIn("decision", properties)
        self.assertNotIn("answer_disposition", properties)
        self.assertNotIn("decision", schema["required"])
        self.assertNotIn("answer_disposition", schema["required"])
        self.assertEqual(properties["canonical_answer"]["minLength"], 1)
        self.assertEqual(properties["canonical_claim"]["minLength"], 1)

    def test_answer_audit_rejects_empty_canonical_answer(self):
        invalid = self._audit(
            answer_disposition="USE_CANONICAL_CORE",
            canonical_answer="",
            candidate_has_removable_additions=True,
        )
        with patch(
            "tools.run_ai_prompt", return_value=invalid
        ), patch("tools.unload_model"):
            result = external_fact_fallback.audit_answer(
                "SNH48目前有哪些正式Team？",
                "SNH48目前有四个正式Team。另有无关说明。",
                {"results": []},
                self._assessment(valid_for_days=180),
            )
        self.assertEqual(result["decision"], "REJECT")
        self.assertEqual(result["answer_disposition"], "REJECT")

    def test_answer_audit_as_is_does_not_duplicate_long_answer(self):
        answer = "因为其肠道的弹性和收缩方式会塑造粪便。"
        valid = self._audit(
            answer_disposition="USE_AS_IS",
            canonical_answer=answer,
            canonical_claim=answer,
            candidate_has_removable_additions=False,
        )
        with patch(
            "tools.run_ai_prompt", return_value=valid
        ), patch("tools.unload_model"):
            result = external_fact_fallback.audit_answer(
                "袋熊的便便为什么是方形的？",
                answer,
                {"results": []},
                self._assessment(knowledge_type="stable", valid_for_days=None),
            )
        self.assertEqual(result["decision"], "AUTO_VERIFY")
        self.assertEqual(result["answer_disposition"], "USE_AS_IS")
        self.assertEqual(result["canonical_answer"], answer)

    def test_positive_findings_override_legacy_global_reject_label(self):
        clean_answer = (
            "SNH48目前有四个正式Team：Team SII、Team NII、"
            "Team HII和Team X。"
        )
        contradictory = self._audit(
            decision="REJECT",
            answer_disposition="REJECT",
            canonical_answer=clean_answer,
            canonical_claim=clean_answer,
            candidate_has_removable_additions=True,
            confidence=1.0,
        )
        with patch(
            "tools.run_ai_prompt", return_value=contradictory
        ) as model, patch("tools.unload_model"):
            result = external_fact_fallback.audit_answer(
                "SNH48目前有哪些正式Team？",
                clean_answer + "一场不存在的活动也证明了这份名单。",
                {"results": []},
                self._assessment(valid_for_days=180),
            )
        self.assertEqual(result["decision"], "AUTO_VERIFY")
        self.assertEqual(
            result["answer_disposition"], "USE_CANONICAL_CORE"
        )
        self.assertEqual(result["canonical_answer"], clean_answer)
        model.assert_called_once()

    def test_named_person_current_team_is_answered_without_knowledge(self):
        assessment = self._assessment(
            outbound_prompt="李艺彤现在属于哪个团体？",
            knowledge_type="changing",
            valid_for_days=None,
        )
        with patch.object(
            external_fact_fallback, "assess_request", return_value=assessment
        ), patch(
            "casper.external_ai.ask_prompt",
            return_value={
                "status": "COMPLETED",
                "answer": "她目前属于示例团体。",
                "provider": "ChatGPT Desktop",
            },
        ), patch.object(
            external_fact_fallback, "audit_answer"
        ) as audit, patch.object(
            knowledge, "apply_external_ai_fact_fallback"
        ) as persist:
            result = external_fact_fallback.attempt(
                "李艺彤现在属于哪个团体？",
                "query",
                {"results": []},
                {"scope_type": "CURRENT_ACTIVE_STATE"},
            )
        self.assertEqual(result["status"], "CURRENT_REFERENCE")
        self.assertEqual(result["knowledge_status"], "not_recorded_time_sensitive")
        audit.assert_not_called()
        persist.assert_not_called()

    def test_mixed_current_answer_can_store_only_ai_partitioned_reusable_claim(self):
        assessment = self._assessment(
            outbound_prompt="SNH48有哪些正式分队，成员现在如何安排？",
            knowledge_type="changing",
            valid_for_days=None,
            has_reusable_component=True,
        )
        partition = {
            "answer_usable": True,
            "directly_answers": True,
            "complete_for_request": True,
            "claims": [{
                "persist": True,
                "directly_supported_by_answer": True,
                "no_evidence_conflict": True,
                "subject": "SNH48正式分队",
                "claim": "SNH48采用固定正式分队组织剧场公演。",
                "knowledge_type": "reviewable",
                "valid_for_days": 180,
                "confidence": 0.9,
                "topics": ["SNH48", "分队"],
                "knowledge_domain": "culture_entertainment",
                "cluster_label": "SNH48",
                "reason": "Reusable structure separated from current roster.",
            }],
            "reason": "Mixed lifecycle split.",
        }
        with patch.object(
            external_fact_fallback, "assess_request", return_value=assessment
        ), patch(
            "casper.external_ai.ask_prompt",
            return_value={
                "status": "COMPLETED",
                "answer": "结构与当前成员安排的完整回答。",
                "provider": "ChatGPT Desktop",
            },
        ), patch.object(
            external_fact_fallback,
            "partition_mixed_answer",
            return_value=partition,
        ), patch.object(
            knowledge,
            "apply_external_ai_partitioned_claim",
            return_value=("verified", {"id": "knowledge-structure"}),
        ) as persist:
            result = external_fact_fallback.attempt(
                "SNH48有哪些正式分队，成员现在如何安排？",
                "query",
                {"results": []},
                {"scope_type": "CURRENT_ACTIVE_STATE"},
            )
        self.assertEqual(result["status"], "CURRENT_REFERENCE")
        self.assertEqual(result["knowledge_status"], "reusable_components_recorded")
        self.assertEqual(result["knowledge_ids"], ["knowledge-structure"])
        persist.assert_called_once()

    def test_independent_partition_audit_corrects_stable_list_to_reviewable(self):
        partition = {
            "answer_usable": True,
            "directly_answers": True,
            "complete_for_request": True,
            "claims": [{
                "persist": True,
                "directly_supported_by_answer": True,
                "no_evidence_conflict": True,
                "subject": "某组织正式单位",
                "claim": "该组织目前共有四个正式单位。",
                "knowledge_type": "stable",
                "valid_for_days": None,
                "confidence": 0.92,
                "topics": ["组织结构"],
                "knowledge_domain": "business_organization",
                "cluster_label": "example_structure",
                "reason": "First partition proposal.",
            }],
            "reason": "First partition.",
        }
        audit = {
            "decisions": [{
                "audit_id": "partition_claim_0",
                "persist": True,
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "knowledge_type": "reviewable",
                "valid_for_days": 180,
                "lifecycle_proportional": True,
                "reason": "A present complete organizational set may change.",
            }],
            "reason": "Independent audit corrected lifecycle.",
        }
        with patch("tools.run_ai_prompt", return_value=audit), patch(
            "tools.unload_model"
        ):
            result = external_fact_fallback.audit_partition_lifecycles(
                "该组织目前有哪些正式单位？",
                "完整回答",
                {"results": []},
                self._assessment(
                    knowledge_type="changing",
                    valid_for_days=None,
                    has_reusable_component=True,
                ),
                partition,
            )
        claim = result["claims"][0]
        self.assertTrue(claim["persist"])
        self.assertEqual(claim["knowledge_type"], "reviewable")
        self.assertEqual(claim["valid_for_days"], 180)
        self.assertEqual(claim["partition_lifecycle_audit_version"], 10)

    def test_final_lifecycle_ai_can_promote_eligible_formal_unit_set(self):
        partition = {
            "answer_usable": True,
            "directly_answers": True,
            "complete_for_request": True,
            "claims": [{
                "persist": False,
                "directly_supported_by_answer": True,
                "no_evidence_conflict": True,
                "subject": "某组织当前正式单位",
                "claim": "截至目前，该组织设有甲、乙、丙、丁四个正式单位。",
                "knowledge_type": "changing",
                "valid_for_days": None,
                "confidence": 0.95,
                "topics": ["组织结构"],
                "knowledge_domain": "business_organization",
                "cluster_label": "example_structure",
                "reason": "The first partitioner treated it as current state.",
            }],
            "reason": "First partition proposal.",
        }
        audit = {
            "decisions": [{
                "audit_id": "partition_claim_0",
                "persist": True,
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "knowledge_type": "reviewable",
                "valid_for_days": 365,
                "lifecycle_proportional": True,
                "reason": (
                    "The named formal units are a maintained organizational "
                    "set, not the people assigned to them."
                ),
            }],
            "reason": "The final lifecycle AI corrected the first proposal.",
        }
        with patch("tools.run_ai_prompt", return_value=audit) as model, patch(
            "tools.unload_model"
        ):
            result = external_fact_fallback.audit_partition_lifecycles(
                "该组织目前有哪些正式单位？",
                "截至目前，该组织设有甲、乙、丙、丁四个正式单位。",
                {"results": []},
                self._assessment(
                    knowledge_type="changing",
                    valid_for_days=None,
                    has_reusable_component=True,
                ),
                partition,
            )
        self.assertEqual(model.call_count, 1)
        claim = result["claims"][0]
        self.assertIs(claim["persist"], True)
        self.assertEqual(claim["lifecycle_basis"], "MAINTAINED_SET_OR_STRUCTURE")
        self.assertEqual(claim["knowledge_type"], "reviewable")
        self.assertEqual(claim["partition_lifecycle_audit_version"], 10)

    def test_final_lifecycle_ai_cannot_promote_ineligible_claim(self):
        partition = {
            "answer_usable": True,
            "directly_answers": True,
            "complete_for_request": True,
            "claims": [{
                "persist": False,
                "directly_supported_by_answer": False,
                "no_evidence_conflict": True,
                "subject": "某组织正式单位",
                "claim": "一个未被答案直接支持的正式单位集合。",
                "knowledge_type": "changing",
                "valid_for_days": None,
                "confidence": 0.95,
                "topics": ["组织结构"],
                "knowledge_domain": "business_organization",
                "cluster_label": "example_structure",
                "reason": "Not directly supported.",
            }],
            "reason": "First partition proposal.",
        }
        invalid_audit = {
            "decisions": [{
                "audit_id": "partition_claim_0",
                "persist": True,
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "knowledge_type": "stable",
                "valid_for_days": None,
                "lifecycle_proportional": True,
                "reason": "Incorrectly attempted to persist an ineligible claim.",
            }],
            "reason": "Invalid eligibility override.",
        }
        with patch(
            "tools.run_ai_prompt",
            side_effect=[invalid_audit, invalid_audit],
        ) as model, patch("tools.unload_model"):
            result = external_fact_fallback.audit_partition_lifecycles(
                "该组织目前有哪些正式单位？",
                "答案没有提供单位集合。",
                {"results": []},
                self._assessment(
                    knowledge_type="changing",
                    valid_for_days=None,
                    has_reusable_component=True,
                ),
                partition,
            )
        self.assertEqual(model.call_count, 2)
        self.assertEqual(result["lifecycle_audit_status"], "FAILED_CLOSED")
        self.assertIs(result["claims"][0]["persist"], False)

    def test_nonproportional_first_audit_is_recovered_by_ai(self):
        partition = {
            "answer_usable": True,
            "directly_answers": True,
            "complete_for_request": True,
            "claims": [{
                "persist": True,
                "directly_supported_by_answer": True,
                "no_evidence_conflict": True,
                "subject": "某组织当前正式单位",
                "claim": "该组织目前共有四个正式单位。",
                "knowledge_type": "stable",
                "valid_for_days": None,
                "confidence": 0.95,
                "topics": ["组织结构"],
                "knowledge_domain": "business_organization",
                "cluster_label": "example_structure",
                "reason": "First partition proposal.",
            }],
            "reason": "First partition.",
        }
        rejected_first = {
            "decisions": [{
                "audit_id": "partition_claim_0",
                "persist": False,
                "lifecycle_basis": "TRANSIENT_CURRENT_STATE_OR_EVENT",
                "knowledge_type": "changing",
                "valid_for_days": None,
                "lifecycle_proportional": False,
                "reason": "Incorrectly treated the unit set as a roster.",
            }],
            "reason": "First audit.",
        }
        recovered = {
            "decisions": [{
                "audit_id": "partition_claim_0",
                "persist": True,
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "knowledge_type": "reviewable",
                "valid_for_days": 180,
                "lifecycle_proportional": True,
                "reason": "Official unit sets are reusable structures.",
            }],
            "reason": "Recovered lifecycle contract.",
        }
        with patch(
            "tools.run_ai_prompt", side_effect=[rejected_first, recovered]
        ) as model, patch("tools.unload_model"):
            result = external_fact_fallback.audit_partition_lifecycles(
                "该组织目前有哪些正式单位？",
                "完整回答",
                {"results": []},
                self._assessment(
                    knowledge_type="changing",
                    valid_for_days=None,
                    has_reusable_component=True,
                ),
                partition,
            )
        self.assertEqual(model.call_count, 2)
        self.assertIn("_recovery.txt", model.call_args_list[1].args[0])
        claim = result["claims"][0]
        self.assertTrue(claim["persist"])
        self.assertEqual(claim["knowledge_type"], "reviewable")
        self.assertEqual(claim["valid_for_days"], 180)
        self.assertEqual(claim["partition_lifecycle_audit_version"], 10)

    def test_maintained_structure_may_remain_stable_without_third_critic(self):
        records = [
            {
                "audit_id": "claim_0",
                "subject": "某组织正式单位",
                "claim": "该组织目前设有甲、乙、丙、丁四个正式单位。",
                "proposed_persist": True,
                "proposed_knowledge_type": "stable",
                "proposed_valid_for_days": None,
                "confidence": 0.95,
            },
            {
                "audit_id": "claim_1",
                "subject": "组织术语定义",
                "claim": "正式单位指承担固定职能的内部组织单元。",
                "proposed_persist": True,
                "proposed_knowledge_type": "stable",
                "proposed_valid_for_days": None,
                "confidence": 0.95,
            },
            {
                "audit_id": "claim_2",
                "subject": "某人当前归属",
                "claim": "某人目前属于甲单位。",
                "proposed_persist": False,
                "proposed_knowledge_type": "changing",
                "proposed_valid_for_days": None,
                "confidence": 0.95,
            },
        ]
        unanimous = {
            "decisions": [
                {
                    "audit_id": "claim_0",
                    "persist": True,
                    "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                    "knowledge_type": "stable",
                    "valid_for_days": None,
                    "lifecycle_proportional": True,
                    "reason": (
                        "This maintained structure changes rarely enough for "
                        "stable storage plus random review."
                    ),
                },
                {
                    "audit_id": "claim_1",
                    "persist": True,
                    "lifecycle_basis": (
                        "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
                    ),
                    "knowledge_type": "stable",
                    "valid_for_days": None,
                    "lifecycle_proportional": True,
                    "reason": "A durable definition.",
                },
                {
                    "audit_id": "claim_2",
                    "persist": False,
                    "lifecycle_basis": "TRANSIENT_CURRENT_STATE_OR_EVENT",
                    "knowledge_type": "changing",
                    "valid_for_days": None,
                    "lifecycle_proportional": True,
                    "reason": "A person's current affiliation can change.",
                },
            ],
            "reason": "Initial unanimous lifecycle decision.",
        }
        criticized = {
            "decisions": [
                {
                    "audit_id": "claim_0",
                    "persist": True,
                    "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                    "knowledge_type": "reviewable",
                    "valid_for_days": 365,
                    "lifecycle_proportional": True,
                    "reason": "A maintained current unit set can change.",
                },
                {
                    "audit_id": "claim_1",
                    "persist": True,
                    "lifecycle_basis": (
                        "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
                    ),
                    "knowledge_type": "stable",
                    "valid_for_days": None,
                    "lifecycle_proportional": True,
                    "reason": "The definition is not an active-state list.",
                },
                {
                    "audit_id": "claim_2",
                    "persist": False,
                    "lifecycle_basis": "TRANSIENT_CURRENT_STATE_OR_EVENT",
                    "knowledge_type": "changing",
                    "valid_for_days": None,
                    "lifecycle_proportional": True,
                    "reason": "The affiliation remains current-turn only.",
                },
            ],
            "reason": "Durability counterfactual applied independently.",
        }
        with patch(
            "tools.run_ai_prompt", side_effect=[unanimous]
        ) as model, patch("tools.unload_model"):
            decisions = external_fact_fallback._run_partition_lifecycle_audit(
                records,
                {"mode": "contract_test"},
            )

        self.assertEqual(model.call_count, 1)
        by_id = {item["audit_id"]: item for item in decisions}
        self.assertEqual(by_id["claim_0"]["knowledge_type"], "stable")
        self.assertIsNone(by_id["claim_0"]["valid_for_days"])
        self.assertEqual(by_id["claim_1"]["knowledge_type"], "stable")
        self.assertEqual(by_id["claim_2"]["knowledge_type"], "changing")
        self.assertFalse(by_id["claim_2"]["persist"])

    def test_verified_browser_correction_uses_ai_partition_and_lifecycle_audit(self):
        partition = {
            "answer_usable": True,
            "directly_answers": True,
            "complete_for_request": True,
            "claims": [{
                "persist": True,
                "directly_supported_by_answer": True,
                "no_evidence_conflict": True,
                "subject": "某组织正式单位",
                "claim": "该组织目前设有五个正式单位。",
                "knowledge_type": "reviewable",
                "valid_for_days": 365,
                "confidence": 0.94,
                "topics": ["组织结构"],
                "knowledge_domain": "business_organization",
                "cluster_label": "example_structure",
                "reason": "Accepted browser answer supports this claim.",
            }],
            "reason": "One reusable correction claim.",
        }
        lifecycle = {
            "decisions": [{
                "audit_id": "partition_claim_0",
                "persist": True,
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "knowledge_type": "reviewable",
                "valid_for_days": 365,
                "lifecycle_proportional": True,
                "reason": "A maintained current unit set needs review.",
            }],
            "reason": "Lifecycle accepted.",
        }
        with patch(
            "tools.run_ai_prompt", side_effect=[partition, lifecycle]
        ) as model, patch("tools.unload_model"):
            result = (
                external_fact_fallback
                .partition_verified_correction_answer(
                    "你之前的正式单位名单不对，请重新核实。",
                    "该组织目前设有五个正式单位。",
                    {
                        "status": "OK",
                        "results": [{
                            "title": "Official structure",
                            "url": "https://example.test/structure",
                            "domain": "example.test",
                        }],
                    },
                    [{
                        "id": "knowledge-old-units",
                        "subject": "某组织正式单位",
                        "claim": "该组织目前设有四个正式单位。",
                    }],
                )
            )

        self.assertEqual(model.call_count, 2)
        self.assertIn(
            "nerv_knowledge_correction_partition.txt",
            model.call_args_list[0].args[0],
        )
        self.assertEqual(result["lifecycle_audit_status"], "PASSED")
        self.assertEqual(
            result["claims"][0]["knowledge_type"],
            "reviewable",
        )
        self.assertEqual(
            result["claims"][0]["partition_lifecycle_audit_version"],
            10,
        )

    def test_partition_prompt_distinguishes_formal_units_from_people_roster(self):
        prompt = (
            Path(__file__).resolve().parents[1]
            / "prompts"
            / "external_fact_fallback_partition.txt"
        ).read_text(encoding="utf-8")
        compact = " ".join(prompt.split())
        self.assertIn("formal-unit inventory", compact)
        self.assertIn("A roster is the people assigned to those units", compact)
        self.assertIn("currently", compact)

    def test_historical_roster_prompts_and_schema_do_not_anchor_to_false(self):
        root = Path(__file__).resolve().parents[1]
        for name in (
            "nerv_fact_lookup_knowledge_partition.txt",
            "external_fact_fallback_partition_lifecycle_audit.txt",
            "external_fact_fallback_partition_lifecycle_audit_recovery.txt",
        ):
            prompt = (root / "prompts" / name).read_text(encoding="utf-8")
            compact = " ".join(prompt.split()).casefold()
            self.assertIn("historical", compact)
            self.assertIn("people", compact)
            self.assertIn("fixed_history", compact)
            self.assertIn("persist=true", compact)
            self.assertIn("completed one-time", compact)
        schema = external_fact_fallback._partition_lifecycle_audit_schema(
            ["partition_claim_0"]
        )
        properties = schema["properties"]["decisions"]["items"]["properties"]
        persist_description = properties["persist"]["description"]
        basis_description = properties["lifecycle_basis"]["description"]
        self.assertIn("even when proposed_persist was false", persist_description)
        self.assertIn("exact people-roster snapshot", basis_description)
        self.assertNotIn(
            "when persistence was originally withheld",
            persist_description,
        )

    def test_lifecycle_auditor_can_correct_false_historical_roster_proposal(self):
        exact_period = "2025 (specifically updated as of November 2025)"
        partition = {
            "answer_usable": True,
            "directly_answers": True,
            "complete_for_request": True,
            "claims": [{
                "persist": False,
                "directly_supported_by_answer": True,
                "no_evidence_conflict": True,
                "subject": "示例联队2025年11月阵容",
                "claim": "截至2025年11月，示例联队成员为球员甲、乙和丙。",
                "knowledge_type": "changing",
                "valid_for_days": None,
                "confidence": 0.95,
                "topics": ["示例联队"],
                "knowledge_domain": "sports",
                "cluster_label": "example_roster",
                "temporal_scope": {
                    "scope_type": "EXPLICIT_PERIOD",
                    "requested_period": exact_period,
                    "allow_previous_period": False,
                },
                "reason": "The first partitioner incorrectly treated all rosters as live.",
            }],
            "reason": "First proposal reproduced from the live failure.",
        }
        corrected = {
            "decisions": [{
                "audit_id": "partition_claim_0",
                "persist": True,
                "lifecycle_basis": "FIXED_HISTORY",
                "knowledge_type": "stable",
                "valid_for_days": None,
                "lifecycle_proportional": True,
                "reason": "An exact completed dated roster is immutable history.",
            }],
            "reason": "Corrected the false current-roster interpretation.",
        }
        with patch("tools.run_ai_prompt", return_value=corrected) as model, patch(
            "tools.unload_model"
        ):
            result = external_fact_fallback.audit_partition_lifecycles(
                "2025年示例联队有哪些球员？",
                "截至2025年11月，示例联队成员为球员甲、乙和丙。",
                {"results": []},
                self._assessment(
                    knowledge_type="changing",
                    valid_for_days=None,
                    has_reusable_component=True,
                ),
                partition,
                additional_context={
                    "source_supported_periods": [exact_period],
                    "strict_source_temporal_scope": True,
                },
            )

        self.assertEqual(model.call_count, 1)
        claim = result["claims"][0]
        self.assertIs(claim["persist"], True)
        self.assertEqual(claim["lifecycle_basis"], "FIXED_HISTORY")
        self.assertEqual(claim["knowledge_type"], "stable")
        self.assertEqual(
            claim["temporal_scope"]["requested_period"],
            exact_period,
        )

    def test_valid_stable_decision_does_not_add_a_third_critic(self):
        records = [{
            "audit_id": "claim_0",
            "subject": "某组织正式单位",
            "claim": "该组织目前设有四个正式单位。",
            "proposed_persist": True,
            "proposed_knowledge_type": "stable",
            "proposed_valid_for_days": None,
            "confidence": 0.95,
        }]
        unanimous = {
            "decisions": [{
                "audit_id": "claim_0",
                "persist": True,
                "lifecycle_basis": (
                    "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
                ),
                "knowledge_type": "stable",
                "valid_for_days": None,
                "lifecycle_proportional": True,
                "reason": "Initial agreement.",
            }],
            "reason": "Initial audit.",
        }
        with patch(
            "tools.run_ai_prompt", side_effect=[unanimous]
        ) as model, patch("tools.unload_model"):
            decisions = external_fact_fallback._run_partition_lifecycle_audit(
                records,
                {"mode": "contract_test"},
            )
        self.assertEqual(model.call_count, 1)
        self.assertEqual(decisions[0]["knowledge_type"], "stable")

    def test_lifecycle_auditor_owns_final_valid_label_without_arbiter(self):
        records = [{
            "audit_id": "claim_0",
            "subject": "某组织当前正式单位",
            "claim": "该组织目前共有四个正式单位。",
            "proposed_persist": True,
            "proposed_knowledge_type": "stable",
            "proposed_valid_for_days": None,
            "confidence": 0.95,
        }]
        reviewable = {
            "decisions": [{
                "audit_id": "claim_0",
                "persist": True,
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "knowledge_type": "reviewable",
                "valid_for_days": 180,
                "lifecycle_proportional": True,
                "reason": "Official unit sets are reusable structures.",
            }],
            "reason": "Reviewable structure.",
        }
        with patch(
            "tools.run_ai_prompt", side_effect=[reviewable]
        ) as model, patch("tools.unload_model"):
            decisions = (
                external_fact_fallback._run_partition_lifecycle_audit(
                    records,
                    {"mode": "contract_test"},
                )
            )
        self.assertEqual(model.call_count, 1)
        self.assertEqual(decisions[0]["knowledge_type"], "reviewable")
        self.assertTrue(decisions[0]["persist"])

    def test_invalid_partition_audit_fails_closed_for_persistence_only(self):
        partition = {
            "answer_usable": True,
            "directly_answers": True,
            "complete_for_request": True,
            "claims": [{
                "persist": True,
                "subject": "主题",
                "claim": "一条回答中的知识。",
                "knowledge_type": "stable",
                "valid_for_days": None,
            }],
            "reason": "First partition.",
        }
        with patch("tools.run_ai_prompt", return_value={}), patch(
            "tools.unload_model"
        ):
            result = external_fact_fallback.audit_partition_lifecycles(
                "问题",
                "回答",
                {"results": []},
                self._assessment(
                    knowledge_type="changing",
                    valid_for_days=None,
                    has_reusable_component=True,
                ),
                partition,
            )
        self.assertTrue(result["answer_usable"])
        self.assertFalse(result["claims"][0]["persist"])
        self.assertEqual(result["lifecycle_audit_status"], "FAILED_CLOSED")

    def test_ai_policy_marks_mixed_request_for_partition(self):
        first = self._assessment(
            knowledge_type="changing",
            valid_for_days=None,
            has_reusable_component=True,
        )
        audited = self._policy_audit(
            knowledge_type="changing",
            valid_for_days=None,
            has_reusable_component=True,
        )
        with patch(
            "tools.run_ai_prompt", side_effect=[first, audited]
        ), patch("tools.unload_model"):
            result = external_fact_fallback.assess_request(
                "SNH48有哪些正式分队，成员现在如何安排？",
                {"scope_type": "CURRENT_ACTIVE_STATE"},
            )
        self.assertEqual(result["knowledge_type"], "changing")
        self.assertIs(result["has_reusable_component"], True)

    def test_changing_ai_ask_with_null_expiry_remains_ask(self):
        result = self._assessment(
            outbound_prompt="李艺彤现在属于哪个团体？",
            knowledge_type="changing",
            valid_for_days=None,
        )
        policy_audit = self._policy_audit(
            outbound_prompt="李艺彤现在属于哪个团体？",
            knowledge_type="changing",
            valid_for_days=None,
        )
        with patch(
            "tools.run_ai_prompt",
            side_effect=[result, policy_audit],
        ), patch(
            "tools.unload_model"
        ):
            decision = external_fact_fallback.assess_request(
                "李艺彤现在属于哪个团体？",
                {"scope_type": "CURRENT_ACTIVE_STATE"},
            )
        self.assertEqual(decision["decision"], "ASK")
        self.assertEqual(decision["knowledge_type"], "changing")
        self.assertIsNone(decision["valid_for_days"])

    def test_normal_public_skip_receives_one_ai_recovery(self):
        first = self._assessment(
            decision="SKIP",
            outbound_prompt="",
            knowledge_type="changing",
            valid_for_days=None,
        )
        recovered = self._assessment(
            outbound_prompt="李艺彤现在属于哪个团体？",
            knowledge_type="changing",
            valid_for_days=None,
        )
        policy_audit = self._policy_audit(
            outbound_prompt="李艺彤现在属于哪个团体？",
            knowledge_type="changing",
            valid_for_days=None,
        )
        with patch(
            "tools.run_ai_prompt",
            side_effect=[first, recovered, policy_audit],
        ) as model, patch("tools.unload_model"):
            decision = external_fact_fallback.assess_request(
                "李艺彤现在属于哪个团体？",
                {"scope_type": "CURRENT_ACTIVE_STATE"},
            )
        self.assertEqual(model.call_count, 3)
        self.assertEqual(decision["decision"], "ASK")
        self.assertEqual(decision["knowledge_type"], "changing")

    def test_independent_ai_corrects_overlong_review_interval(self):
        first = self._assessment(valid_for_days=3650)
        audited = self._policy_audit(valid_for_days=180)
        with patch(
            "tools.run_ai_prompt",
            side_effect=[first, audited],
        ) as model, patch("tools.unload_model"):
            decision = external_fact_fallback.assess_request(
                "SNH48有哪些正式分队？",
                {"scope_type": "CURRENT_ACTIVE_STATE"},
            )
        self.assertEqual(model.call_count, 2)
        self.assertEqual(decision["decision"], "ASK")
        self.assertEqual(decision["knowledge_type"], "reviewable")
        self.assertEqual(decision["valid_for_days"], 180)

    def test_stable_or_reviewable_low_impact_answer_enters_knowledge(self):
        assessment = self._assessment()
        with patch.object(
            external_fact_fallback, "assess_request", return_value=assessment
        ), patch(
            "casper.external_ai.ask_prompt",
            return_value={
                "status": "COMPLETED",
                "answer": "SNH48的正式分队为Team SII、NII、HII和X。",
                "provider": "ChatGPT Desktop",
            },
        ), patch.object(
            external_fact_fallback, "audit_answer", return_value=self._audit()
        ), patch.object(
            knowledge,
            "apply_external_ai_fact_fallback",
            return_value=("verified", {"id": "knowledge-snh"}),
        ) as persist:
            result = external_fact_fallback.attempt(
                "SNH48有哪些正式分队？",
                "query",
                {"results": []},
                {"scope_type": "CURRENT_ACTIVE_STATE"},
            )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["knowledge_id"], "knowledge-snh")
        persist.assert_called_once()

    def test_canonical_core_replaces_noisy_answer_for_reply_and_knowledge(self):
        assessment = self._assessment(valid_for_days=180)
        noisy_answer = (
            "截至2026年8月，SNH48目前有四个正式Team：Team SII、"
            "Team NII、Team HII和Team X。某场并不存在的活动也证明了"
            "这一点。"
        )
        clean_answer = (
            "SNH48目前有四个正式Team：Team SII、Team NII、"
            "Team HII和Team X。"
        )
        audit_result = self._audit(
            answer_disposition="USE_CANONICAL_CORE",
            canonical_answer=clean_answer,
            canonical_claim=clean_answer,
            candidate_has_removable_additions=True,
        )
        with patch.object(
            external_fact_fallback, "assess_request", return_value=assessment
        ), patch(
            "casper.external_ai.ask_prompt",
            return_value={
                "status": "COMPLETED",
                "answer": noisy_answer,
                "provider": "ChatGPT Desktop",
            },
        ), patch.object(
            external_fact_fallback,
            "audit_answer",
            return_value=audit_result,
        ), patch.object(
            knowledge,
            "apply_external_ai_fact_fallback",
            return_value=("verified", {"id": "knowledge-clean"}),
        ) as persist:
            result = external_fact_fallback.attempt(
                "SNH48目前有哪些正式Team？",
                "query",
                {"results": []},
                {"scope_type": "CURRENT_ACTIVE_STATE"},
            )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["answer"], clean_answer)
        self.assertNotIn("不存在", result["answer"])
        self.assertEqual(persist.call_args.kwargs["answer"], clean_answer)

    def test_contract_question_requires_second_certification_and_no_knowledge(self):
        assessment = self._assessment(
            importance="HIGH",
            outbound_prompt="这条合同款项需要注意什么？",
            knowledge_type="stable",
            valid_for_days=None,
        )
        first = {
            "status": "COMPLETED",
            "answer": "初步合同说明。",
            "provider": "ChatGPT Desktop",
        }
        second = {
            "status": "COMPLETED",
            "answer": "二次核验后的合同说明。",
            "provider": "ChatGPT Desktop",
        }
        with patch.object(
            external_fact_fallback, "assess_request", return_value=assessment
        ), patch(
            "casper.external_ai.ask_prompt", side_effect=[first, second]
        ) as external, patch.object(
            external_fact_fallback,
            "audit_answer",
            return_value=self._audit(
                subject="合同条款",
                canonical_claim="二次核验后的合同说明。",
            ),
        ) as audit, patch.object(
            knowledge, "apply_external_ai_fact_fallback"
        ) as persist:
            result = external_fact_fallback.attempt(
                "这条合同款项需要注意什么？",
                "query",
                {"results": []},
                {"scope_type": "GENERAL"},
            )
        self.assertEqual(result["status"], "CERTIFIED")
        self.assertEqual(result["answer"], "二次核验后的合同说明。")
        self.assertEqual(external.call_count, 2)
        self.assertTrue(
            audit.call_args.kwargs["certification_context"]["performed"]
        )
        persist.assert_not_called()

    def test_credentials_are_blocked_before_any_model_or_external_call(self):
        with patch("tools.run_ai_prompt") as model:
            result = external_fact_fallback.assess_request(
                "帮我确认银行卡号和登录密码是否正确",
                {"scope_type": "GENERAL"},
            )
        self.assertEqual(result["decision"], "SKIP")
        model.assert_not_called()


class ExternalFactFallbackKnowledgeTests(unittest.TestCase):
    def _audit(self):
        return {
            "decision": "AUTO_VERIFY",
            "answer_disposition": "USE_AS_IS",
            "directly_answers": True,
            "complete_for_request": True,
            "policy_satisfied": True,
            "no_evidence_conflict": True,
            "candidate_has_removable_additions": False,
            "confidence": 0.9,
            "subject": "SNH48正式分队",
            "canonical_answer": "SNH48有四个正式分队。",
            "canonical_claim": "SNH48有四个正式分队。",
            "topics": ["SNH48"],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "SNH48",
            "reason": "reviewable structural fact",
        }

    def test_reviewable_knowledge_has_expiry_and_is_active(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.multiple(
                knowledge,
                DATA_DIR=str(root),
                KNOWLEDGE_FILE=str(root / "knowledge.json"),
                SOURCES_FILE=str(root / "knowledge_sources.json"),
                LOGS_FILE=str(root / "learning_logs.json"),
                PENDING_SOURCES_FILE=str(root / "pending.json"),
            ), patch.object(
                knowledge, "_clusters_file", return_value=str(root / "clusters.json")
            ):
                status, item = knowledge.apply_external_ai_fact_fallback(
                    user_request="SNH48有哪些正式分队？",
                    answer="SNH48有四个正式分队。",
                    assessment={
                        "decision": "ASK",
                        "importance": "LOW",
                        "sharing_risk": "NORMAL",
                        "knowledge_type": "reviewable",
                        "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                        "valid_for_days": 90,
                    },
                    audit=self._audit(),
                )
                active = knowledge.load_active_items()
        self.assertEqual(status, "verified")
        self.assertEqual(item["knowledge_type"], "reviewable")
        self.assertEqual(
            item["lifecycle_audit"]["basis"],
            "MAINTAINED_SET_OR_STRUCTURE",
        )
        self.assertEqual(item["valid_for_days"], 90)
        self.assertTrue(item["expires_at"])
        self.assertEqual(len(active), 1)

    def test_expired_reviewable_knowledge_is_not_recalled(self):
        expired = {
            "id": "knowledge-expired",
            "subject": "SNH48正式分队",
            "claim": "旧的分队结构",
            "status": "verified",
            "knowledge_type": "reviewable",
            "expires_at": (
                datetime.now(timezone.utc) - timedelta(days=1)
            ).isoformat(),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.multiple(
                knowledge,
                DATA_DIR=str(root),
                KNOWLEDGE_FILE=str(root / "knowledge.json"),
                SOURCES_FILE=str(root / "knowledge_sources.json"),
                LOGS_FILE=str(root / "learning_logs.json"),
                PENDING_SOURCES_FILE=str(root / "pending.json"),
            ), patch.object(
                knowledge, "_clusters_file", return_value=str(root / "clusters.json")
            ):
                knowledge.initialize()
                knowledge._save_knowledge([expired])
                active = knowledge.load_active_items()
        self.assertEqual(active, [])

    def test_closed_roster_snapshots_keep_distinct_period_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.multiple(
                knowledge,
                DATA_DIR=str(root),
                KNOWLEDGE_FILE=str(root / "knowledge.json"),
                SOURCES_FILE=str(root / "knowledge_sources.json"),
                LOGS_FILE=str(root / "learning_logs.json"),
                PENDING_SOURCES_FILE=str(root / "pending.json"),
            ), patch.object(
                knowledge, "_clusters_file", return_value=str(root / "clusters.json")
            ):
                knowledge.initialize()
                audit = self._audit()
                audit.update({
                    "subject": "曼联赛季阵容",
                    "canonical_answer": "该赛季结束时的一线队阵容如答案所列。",
                    "canonical_claim": "该赛季结束时的一线队阵容如答案所列。",
                    "topics": ["曼联", "历史阵容"],
                    "knowledge_domain": "sports",
                    "cluster_label": "Manchester United",
                })
                items = []
                for year in ("2024", "2025"):
                    status, item = knowledge.apply_external_ai_fact_fallback(
                        user_request=f"曼联{year}赛季结束时的阵容？",
                        answer=audit["canonical_answer"],
                        assessment={
                            "decision": "ASK",
                            "importance": "LOW",
                            "sharing_risk": "NORMAL",
                            "knowledge_type": "stable",
                            "lifecycle_basis": "FIXED_HISTORY",
                            "valid_for_days": None,
                            "temporal_scope": {
                                "scope_type": "EXPLICIT_PERIOD",
                                "requested_period": f"completed {year} season",
                                "allow_previous_period": False,
                            },
                        },
                        audit=audit,
                    )
                    self.assertEqual(status, "verified")
                    items.append(item)

                stored = knowledge.load_items()

        self.assertNotEqual(items[0]["id"], items[1]["id"])
        self.assertEqual(len(stored), 2)
        self.assertEqual(
            {item["temporal_scope"]["requested_period"] for item in stored},
            {"completed 2024 season", "completed 2025 season"},
        )

    def test_fixed_history_without_closed_period_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.multiple(
                knowledge,
                DATA_DIR=str(root),
                KNOWLEDGE_FILE=str(root / "knowledge.json"),
                SOURCES_FILE=str(root / "knowledge_sources.json"),
                LOGS_FILE=str(root / "learning_logs.json"),
                PENDING_SOURCES_FILE=str(root / "pending.json"),
            ), patch.object(
                knowledge, "_clusters_file", return_value=str(root / "clusters.json")
            ):
                status, item = knowledge.apply_external_ai_fact_fallback(
                    user_request="某队过去的阵容？",
                    answer="历史阵容答案。",
                    assessment={
                        "decision": "ASK",
                        "importance": "LOW",
                        "sharing_risk": "NORMAL",
                        "knowledge_type": "stable",
                        "lifecycle_basis": "FIXED_HISTORY",
                        "valid_for_days": None,
                    },
                    audit=self._audit(),
                )

        self.assertEqual((status, item), ("rejected", None))


class ExternalFactFallbackBrowserTests(unittest.TestCase):
    def test_no_web_result_can_return_each_governed_external_answer_type(self):
        for status in ("VERIFIED", "CURRENT_REFERENCE", "CERTIFIED"):
            with self.subTest(status=status), patch.object(
                browser,
                "_plan_fact_intent_scope",
                return_value={"scope_type": "CURRENT_ACTIVE_STATE"},
            ), patch.object(
                browser,
                "_plan_fact_entity_scope",
                return_value={
                    "target_entity": "Example",
                    "requested_relation": "fact",
                    "required_facets": ["fact"],
                    "included_scope": "Example fact",
                    "excluded_adjacent_scopes": [],
                    "reason": "test",
                },
            ), patch.object(
                browser,
                "_audit_fact_search_query",
                return_value={
                    "decision": "USE",
                    "proposed_query_scope_match": True,
                    "approved_query_scope_match": True,
                    "approved_search_query": "query",
                    "reason": "test",
                },
            ), patch.object(
                browser, "discover_web", return_value={"status": "OK", "results": []}
            ), patch(
                "nerv.external_fact_fallback.attempt",
                return_value={
                    "status": status,
                    "answer": "外部AI回答",
                    "knowledge_id": "knowledge-1",
                },
            ):
                result = browser.fact_lookup_controller(
                    "query",
                    user_request="问题",
                )
            self.assertEqual(result["status"], "OK")
            self.assertEqual(result["direct_reply"], "外部AI回答")
            self.assertTrue(result["answers"][0]["accepted"])


if __name__ == "__main__":
    unittest.main()
