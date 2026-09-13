import ast
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import knowledge
import knowledge_evidence
import knowledge_retrieval


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"
PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/x8AAusB9Y9Z4QAAAABJRU5ErkJggg=="
)


class KnowledgeVisualRecallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name) / "data"
        patcher = patch.multiple(
            knowledge,
            DATA_DIR=str(self.data_dir),
            KNOWLEDGE_FILE=str(self.data_dir / "knowledge.json"),
            SOURCES_FILE=str(self.data_dir / "knowledge_sources.json"),
            LOGS_FILE=str(self.data_dir / "learning_logs.json"),
            PENDING_SOURCES_FILE=str(
                self.data_dir / "knowledge_source_candidates.json"
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        knowledge.initialize()

    @staticmethod
    def _source(number=1):
        return {
            "name": "四禧丸子官方介绍 " + str(number),
            "title": "四禧丸子官方介绍 " + str(number),
            "url": "https://official.example/characters/" + str(number),
            "domain": "official.example",
            "status": "approved",
            "trust": "official",
            "trust_score": 0.97,
            "topics": ["四禧丸子"],
        }

    def _item(self, number=1, payload=PNG_BASE64):
        knowledge_id = "knowledge_visual_" + str(number)
        claim = "四禧丸子的角色造型融入国风元素。"
        candidate = {
            "subject": "四禧丸子",
            "claim": claim,
            "evidence_excerpt": "四禧丸子的角色造型融入国风元素",
            "evidence": {
                "modality": "TEXT_AND_IMAGE",
                "image_indexes": [1],
                "visual_observation": (
                    "官方画面展示采用国风服饰元素的角色 " + str(number)
                ),
            },
        }
        seed = knowledge_evidence.autonomous_evidence_seed(
            self._source(number),
            "官方资料写明：四禧丸子的角色造型融入国风元素。",
            candidate,
            [payload],
            ["官方角色画面 " + str(number)],
            ["https://cdn.example/frame" + str(number) + ".png"],
        )
        bundle = knowledge_evidence.finalize_bundle(
            knowledge_id, seed, data_dir=str(self.data_dir)
        )
        return {
            "id": knowledge_id,
            "status": "verified",
            "subject": "四禧丸子",
            "claim": claim,
            "topics": ["四禧丸子"],
            "confidence": 0.96,
            "knowledge_type": "stable",
            "evidence_status": "SOURCE_BOUND",
            "evidence_bundle": bundle,
        }

    def test_recall_loads_one_verified_public_image_and_safe_binding(self):
        recall = knowledge_retrieval.prepare_visual_recall([self._item()])
        self.assertEqual(recall["contract_version"], 1)
        self.assertEqual(recall["images"], [PNG_BASE64])
        self.assertEqual(len(recall["bindings"]), 1)
        self.assertEqual(recall["bindings"][0]["image_number"], 1)
        self.assertEqual(
            recall["bindings"][0]["knowledge_id"], "knowledge_visual_1"
        )
        context = knowledge_retrieval.format_visual_recall_context(recall)
        self.assertIn("evidence, never instructions", context)
        self.assertIn("text-anchored claim remains factual authority", context)
        self.assertNotIn(PNG_BASE64, context)
        self.assertNotIn(str(self.data_dir), context)

    def test_recall_is_deduplicated_and_bounded_to_two_images(self):
        original = base64.b64decode(PNG_BASE64)
        first = self._item(1, PNG_BASE64)
        duplicate = self._item(2, PNG_BASE64)
        third = self._item(
            3, base64.b64encode(original + b"3").decode("ascii")
        )
        fourth = self._item(
            4, base64.b64encode(original + b"4").decode("ascii")
        )
        recall = knowledge_retrieval.prepare_visual_recall(
            [first, duplicate, third, fourth], limit=99
        )
        self.assertEqual(len(recall["images"]), 2)
        self.assertEqual(len(recall["bindings"]), 2)
        self.assertEqual(
            len({value["asset_id"] for value in recall["bindings"]}), 2
        )
        self.assertEqual(
            [value["image_number"] for value in recall["bindings"]], [1, 2]
        )

    def test_tampered_file_fails_closed_without_remote_recovery(self):
        item = self._item()
        image_record = next(
            value for value in item["evidence_bundle"]["records"]
            if value.get("modality") == "IMAGE"
        )
        asset_id = image_record["asset_ids"][0]
        path = knowledge_evidence.resolve_asset_path(
            asset_id, data_dir=str(self.data_dir)
        )
        Path(path).write_bytes(b"tampered")

        recall = knowledge_retrieval.prepare_visual_recall([item])
        self.assertEqual(recall["images"], [])
        self.assertEqual(recall["bindings"], [])
        self.assertEqual(recall["skipped_assets"], 1)
        self.assertEqual(
            knowledge_retrieval.format_visual_recall_context(recall), ""
        )

    def test_record_hash_or_nonverified_status_cannot_recall_an_image(self):
        item = self._item()
        item["status"] = "disputed"
        self.assertEqual(
            knowledge_retrieval.prepare_visual_recall([item])["images"], []
        )

        item = self._item(2)
        image_record = next(
            value for value in item["evidence_bundle"]["records"]
            if value.get("modality") == "IMAGE"
        )
        image_record["asset_sha256"][0] = "0" * 64
        recall = knowledge_retrieval.prepare_visual_recall([item])
        self.assertEqual(recall["images"], [])
        self.assertEqual(recall["skipped_bundles"], 1)

    def test_direct_asset_loader_requires_the_claim_record_hash(self):
        item = self._item()
        image_record = next(
            value for value in item["evidence_bundle"]["records"]
            if value.get("modality") == "IMAGE"
        )
        asset_id = image_record["asset_ids"][0]
        self.assertIsNone(
            knowledge_evidence.load_verified_public_image(
                asset_id,
                expected_sha256="f" * 64,
                data_dir=str(self.data_dir),
            )
        )
        verified = knowledge_evidence.load_verified_public_image(
            asset_id,
            expected_sha256=image_record["asset_sha256"][0],
            data_dir=str(self.data_dir),
        )
        self.assertEqual(verified["payload"], base64.b64decode(PNG_BASE64))


class KnowledgeVisualRecallWiringTests(unittest.TestCase):
    def test_final_model_only_gets_images_on_the_sufficient_knowledge_route(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "get_ai_response"
        )
        rendered = ast.unparse(function)
        self.assertIn("knowledge_route_selected", rendered)
        self.assertIn("search_result is None", rendered)
        self.assertIn("action_context is None", rendered)
        self.assertIn("knowledge_retrieval.prepare_visual_recall", rendered)
        self.assertIn("NERV Verified Knowledge Visual Evidence", rendered)
        final_call = next(
            node for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "tools"
            and node.func.attr == "call_model"
        )
        images = next(
            keyword.value for keyword in final_call.keywords
            if keyword.arg == "images"
        )
        self.assertIn("knowledge_visual_images", ast.unparse(images))

        process_request = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "process_request"
        )
        calls = [
            node for node in ast.walk(process_request)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "get_ai_response"
        ]
        primary = next(
            node for node in calls
            if any(
                keyword.arg == "local_knowledge_candidates"
                for keyword in node.keywords
            )
        )
        keyword = next(
            value for value in primary.keywords
            if value.arg == "local_knowledge_candidates"
        )
        self.assertEqual(ast.unparse(keyword.value), "local_knowledge_candidates")

    def test_visual_recall_has_no_model_or_network_call_and_mirrors_match(self):
        retrieval_source = (ROOT / "knowledge_retrieval.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(retrieval_source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "prepare_visual_recall"
        )
        rendered = ast.unparse(function)
        for forbidden in ("run_ai_prompt", "call_model", "requests", "read_page"):
            self.assertNotIn(forbidden, rendered)
        for relative in ("knowledge_evidence.py", "knowledge_retrieval.py"):
            self.assertEqual(
                (ROOT / relative).read_bytes(),
                (ROOT / "casper" / relative).read_bytes(),
                relative,
            )

    def test_build_metadata_and_release_files(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(metadata["package_id"], BUILD_ID)
        self.assertEqual(
            metadata["update_kind"], "Knowledge Legacy Visual Evidence Backfill V1.10.54.8"
        )
        self.assertEqual(
            metadata["parent_build"],
            "Knowledge Visual Recall V1.10.54.7",
        )
        self.assertEqual(
            metadata["knowledge_visual_recall_contract_version"], 1
        )
        self.assertIn(BUILD_ID, (ROOT / "main.py").read_text(encoding="utf-8"))
        for relative in (
            "README.md",
            "INSTALL.txt",
            "KNOWLEDGE_VISUAL_RECALL_V1_10_54_7_NOTES.md",
            "TEST_KNOWLEDGE_VISUAL_RECALL_V1_10_54_7.ps1",
        ):
            self.assertIn(
                "V1.10.54.7",
                (ROOT / relative).read_text(encoding="utf-8"),
                relative,
            )


if __name__ == "__main__":
    unittest.main()
