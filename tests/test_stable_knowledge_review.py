from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import knowledge
from nerv.stable_knowledge_review import StableKnowledgeReviewer


class _HighestWeightRng:
    def __init__(self):
        self.weights = []

    def choices(self, population, weights, k):
        self.weights = list(weights)
        index = self.weights.index(max(self.weights))
        return [population[index]]


class StableKnowledgeReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        patcher = patch.multiple(
            knowledge,
            DATA_DIR=str(root),
            KNOWLEDGE_FILE=str(root / "knowledge.json"),
            SOURCES_FILE=str(root / "knowledge_sources.json"),
            LOGS_FILE=str(root / "learning_logs.json"),
            PENDING_SOURCES_FILE=str(
                root / "knowledge_source_candidates.json"
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        knowledge.initialize()

    @staticmethod
    def _item(item_id, basis, claim="A stored stable claim."):
        old = datetime.now(timezone.utc) - timedelta(days=90)
        return {
            "id": item_id,
            "subject": "Stable subject",
            "claim": claim,
            "topics": [],
            "knowledge_domain": "other",
            "cluster_label": "stable subject",
            "learned_at": old.isoformat(),
            "confidence": 0.94,
            "knowledge_type": "stable",
            "valid_for_days": None,
            "expires_at": None,
            "risk": "low",
            "status": "verified",
            "verification_status": "TEST_VERIFIED",
            "provenance": {"origin": "contract_test"},
            "lifecycle_audit": {
                "status": "PASSED",
                "basis": basis,
                "reason": "Synthetic lifecycle basis.",
            },
        }

    @staticmethod
    def _search_result(two_sources=False):
        results = [{
            "title": "Official source",
            "domain": "official.example",
            "url": "https://official.example/fact",
            "source_score": 95,
            "page_success": True,
        }]
        if two_sources:
            results.append({
                "title": "Independent source",
                "domain": "research.example",
                "url": "https://research.example/fact",
                "source_score": 88,
                "page_success": True,
            })
        return {
            "status": "OK",
            "query": "stable fact official source",
            "results": results,
            "answers": [
                {"index": 1, "answer": "Direct evidence about the exact fact."},
                *(
                    [{"index": 2, "answer": "Independent direct evidence."}]
                    if two_sources else []
                ),
            ],
            "judgment": {
                "consensus": two_sources,
                "votes": 2 if two_sources else 1,
                "need_more_sources": not two_sources,
            },
        }

    def test_random_sampler_weights_ai_selected_maintained_basis_higher(self):
        fixed = self._item("knowledge-fixed", "FIXED_HISTORY")
        maintained = self._item(
            "knowledge-maintained",
            "MAINTAINED_SET_OR_STRUCTURE",
        )
        knowledge._save_knowledge([fixed, maintained])
        rng = _HighestWeightRng()
        selected = knowledge.select_stable_review_candidate(rng=rng)
        self.assertEqual(selected["id"], "knowledge-maintained")
        self.assertEqual(sorted(rng.weights), [1, 6])

    def test_supported_random_review_never_rewrites_claim(self):
        item = self._item(
            "knowledge-supported",
            "MAINTAINED_SET_OR_STRUCTURE",
            "The organization uses four official units.",
        )
        knowledge._save_knowledge([item])
        model = Mock(return_value={
            "decision": "SUPPORTED",
            "exact_claim_checked": True,
            "no_silent_replacement": True,
            "reason": "The readable official evidence supports the exact claim.",
        })
        reviewer = StableKnowledgeReviewer(model)
        with patch("tools.build_claim_query", return_value="query"), patch(
            "tools.search_controller",
            return_value=self._search_result(),
        ):
            result = reviewer.run_once(force=True)
        self.assertEqual(result["status"], "SUPPORTED")
        stored = knowledge.load_items()[0]
        self.assertEqual(
            stored["claim"],
            "The organization uses four official units.",
        )
        self.assertEqual(stored["status"], "verified")
        self.assertEqual(
            stored["stable_review"]["last_outcome"],
            "SUPPORTED",
        )

    def test_strong_contradiction_quarantines_without_replacement(self):
        item = self._item(
            "knowledge-contradicted",
            "MAINTAINED_SET_OR_STRUCTURE",
            "The organization uses four official units.",
        )
        knowledge._save_knowledge([item])
        model = Mock(return_value={
            "decision": "CONTRADICTED",
            "exact_claim_checked": True,
            "no_silent_replacement": True,
            "reason": "Two independent readable sources directly contradict it.",
        })
        reviewer = StableKnowledgeReviewer(model)
        with patch("tools.build_claim_query", return_value="query"), patch(
            "tools.search_controller",
            return_value=self._search_result(two_sources=True),
        ):
            result = reviewer.run_once(force=True)
        self.assertEqual(result["status"], "CONTRADICTED")
        stored = knowledge.load_items()[0]
        self.assertEqual(
            stored["claim"],
            "The organization uses four official units.",
        )
        self.assertEqual(stored["status"], "disputed")
        self.assertFalse(stored["dispute"]["replacement_applied"])
        self.assertEqual(knowledge.load_active_items(), [])

    def test_weak_contradiction_is_only_insufficient_evidence(self):
        item = self._item(
            "knowledge-weak",
            "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM",
        )
        knowledge._save_knowledge([item])
        model = Mock(return_value={
            "decision": "CONTRADICTED",
            "exact_claim_checked": True,
            "no_silent_replacement": True,
            "reason": "The single page appears different.",
        })
        reviewer = StableKnowledgeReviewer(model)
        with patch("tools.build_claim_query", return_value="query"), patch(
            "tools.search_controller",
            return_value=self._search_result(),
        ):
            result = reviewer.run_once(force=True)
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")
        stored = knowledge.load_items()[0]
        self.assertEqual(stored["status"], "verified")
        self.assertEqual(
            stored["stable_review"]["last_outcome"],
            "INSUFFICIENT_EVIDENCE",
        )
