import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import knowledge
import knowledge_ai
import knowledge_evidence
import knowledge_retrieval
import knowledge_worker
import tools


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"

# Valid 1 x 1 PNG.  The fixture stays tiny while exercising the exact same
# base64/signature/hash path used for bounded public-source screenshots.
PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/x8AAusB9Y9Z4QAAAABJRU5ErkJggg=="
)


class KnowledgeEvidenceLineageV110545Tests(unittest.TestCase):
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
    def _source(**overrides):
        source = {
            "title": "四禧丸子官方介绍",
            "name": "四禧丸子官方介绍",
            "description": "官方角色与世界观介绍",
            "url": "https://www.bilibili.com/video/BV1public/",
            "domain": "bilibili.com",
            "status": "approved",
            "trust_score": 0.95,
        }
        source.update(overrides)
        return source

    @staticmethod
    def _candidate():
        return {
            "persist": True,
            "directly_supported_by_answer": True,
            "no_evidence_conflict": True,
            "partition_lifecycle_audit_version": (
                knowledge.PARTITION_LIFECYCLE_AUDIT_VERSION
            ),
            "lifecycle_audit_status": "PASSED",
            "confidence": 0.96,
            "knowledge_type": "stable",
            "lifecycle_basis": (
                "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
            ),
            "valid_for_days": None,
            "subject": "四禧丸子",
            "claim": "四禧丸子的角色造型融入国风元素。",
            "topics": ["四禧丸子", "虚拟偶像"],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "四禧丸子",
            "reason": "The accepted official source directly supports it.",
        }

    @classmethod
    def _search_result(cls, *, source=None, modality="TEXT_AND_IMAGE"):
        source = dict(source or cls._source())
        source.update({
            "page_success": True,
            "page_content": (
                "官方介绍：四禧丸子的角色造型融入国风元素，"
                "背景故事围绕禧運楼展开。"
            ),
            "page_images": [PNG_BASE64],
            "page_image_labels": ["官方角色介绍画面"],
        })
        return {
            "status": "SUCCESS",
            "query": "四禧丸子 官方角色造型",
            "results": [source],
            "answers": [{
                "index": 1,
                "answer": "四禧丸子的角色造型融入国风元素。",
                "accepted": True,
                "evidence": {
                    "modality": modality,
                    "text_excerpt": "四禧丸子的角色造型融入国风元素",
                    "image_indexes": [1] if "IMAGE" in modality else [],
                    "visual_observation": (
                        "官方介绍画面展示了四名采用国风服饰元素的角色。"
                        if "IMAGE" in modality else ""
                    ),
                },
            }],
            "judgment": {
                "canonical_answer": "四禧丸子的角色造型融入国风元素。"
            },
        }

    def test_literal_text_seed_is_source_bound(self):
        source = self._source()
        page = "A段。四禧丸子的角色造型融入国风元素。B段。"
        seed = knowledge_evidence.text_evidence_seed(
            source, page, "四禧丸子的角色造型融入国风元素"
        )
        self.assertTrue(seed["records"])
        self.assertTrue(knowledge_evidence.seed_fingerprint(seed))
        self.assertIsNone(
            knowledge_evidence.text_evidence_seed(
                source, page, "页面没有写出的推测"
            )
        )

    def test_private_or_user_supplied_image_is_never_cached(self):
        for source in (
            self._source(url="file:///C:/private/photo.png"),
            self._source(
                privacy_class="PRIVATE_MEDIA",
                source_origin="USER_UPLOAD",
                user_supplied=True,
            ),
        ):
            seed = knowledge_evidence.search_result_evidence_seed(
                self._search_result(source=source),
                accepted_only=True,
            )
            self.assertEqual(seed, {})
        index = knowledge_evidence.load_media_index(str(self.data_dir))
        self.assertEqual(index["assets"], {})

    def test_source_extractor_keeps_only_exact_text_and_selected_frame(self):
        source = self._search_result()["results"][0]
        with patch.object(
            tools,
            "run_ai_prompt",
            return_value={
                "answer": "四禧丸子的角色造型融入国风元素。",
                "evidence": {
                    "modality": "TEXT_AND_IMAGE",
                    "text_excerpt": "四禧丸子的角色造型融入国风元素",
                    "image_indexes": [1],
                    "visual_observation": "画面展示国风服饰角色。",
                },
            },
        ) as model:
            result = tools.extract_answers("角色造型是什么？", [source])
        self.assertEqual(result[0]["evidence"]["modality"], "TEXT_AND_IMAGE")
        self.assertEqual(result[0]["evidence"]["image_indexes"], [1])
        self.assertEqual(model.call_args.kwargs["images"], [PNG_BASE64])
        self.assertEqual(
            model.call_args.kwargs["json_schema"],
            tools._SINGLE_SOURCE_EXTRACTION_SCHEMA,
        )

    def test_extractor_downgrades_unbound_model_evidence(self):
        source = self._search_result()["results"][0]
        normalized = tools._normalize_single_source_extraction(
            {
                "answer": "模型自己补出的答案",
                "evidence": {
                    "modality": "TEXT_AND_IMAGE",
                    "text_excerpt": "页面不存在的句子",
                    "image_indexes": [9],
                    "visual_observation": "没有绑定任何真实图片。",
                },
            },
            source,
        )
        self.assertEqual(normalized["evidence"]["modality"], "NONE")
        self.assertEqual(normalized["evidence"]["text_excerpt"], "")
        self.assertEqual(normalized["evidence"]["image_indexes"], [])

    def test_autonomous_extraction_requires_literal_excerpt(self):
        source = self._source()
        page = "官方资料写明：四禧丸子的角色造型融入国风元素。"
        valid = {
            "subject": "四禧丸子",
            "claim": "四禧丸子的角色造型融入国风元素。",
            "evidence_excerpt": "四禧丸子的角色造型融入国风元素",
        }
        with patch.object(
            tools, "run_ai_prompt", return_value={"items": [valid]}
        ):
            candidates = knowledge_worker.extract_candidates(source, page, [])
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0]["_evidence_fingerprint"])

        invalid = dict(valid)
        invalid["claim"] = "该组合的风格非常受欢迎。"
        invalid["evidence_excerpt"] = "受欢迎程度很高"
        with patch.object(
            tools, "run_ai_prompt", return_value={"items": [invalid]}
        ):
            self.assertEqual(
                knowledge_worker.extract_candidates(source, page, []), []
            )

    def test_judge_schema_binds_the_exact_evidence_snapshot(self):
        seed = knowledge_evidence.text_evidence_seed(
            self._source(),
            "四禧丸子的角色造型融入国风元素。",
            "四禧丸子的角色造型融入国风元素",
        )
        fingerprint = knowledge_evidence.seed_fingerprint(seed)
        schema = knowledge_ai._knowledge_judge_schema(
            "knowledge_candidate", fingerprint
        )
        self.assertIn("evidence_fingerprint", schema["required"])
        self.assertEqual(
            schema["properties"]["evidence_fingerprint"]["enum"],
            [fingerprint],
        )

    def test_verified_fact_persists_text_and_public_image_lineage(self):
        status, item = knowledge.apply_verified_fact_lookup_partitioned_claim(
            "请查四禧丸子的官方造型",
            "四禧丸子的角色造型融入国风元素。",
            self._candidate(),
            self._search_result(),
        )
        self.assertEqual(status, "verified")
        bundle = item["evidence_bundle"]
        self.assertEqual(bundle["modalities"], ["IMAGE", "TEXT"])
        self.assertEqual(bundle["claim_id"], item["id"])
        self.assertEqual(
            knowledge_evidence.validate_bundle(
                bundle,
                knowledge_evidence.load_media_index(
                    str(self.data_dir)
                )["assets"],
            ),
            [],
        )

        detail = knowledge.load_knowledge_evidence(
            item["id"], include_asset_paths=True
        )
        self.assertEqual(detail["evidence_status"], "SOURCE_BOUND")
        self.assertEqual(len(detail["assets"]), 1)
        self.assertTrue(Path(detail["assets"][0]["resolved_path"]).is_file())
        self.assertNotIn(PNG_BASE64, json.dumps(detail, ensure_ascii=False))
        context = knowledge_retrieval.format_fast_context([item])
        self.assertIn("官方介绍画面展示了四名", context)
        self.assertNotIn(PNG_BASE64, context)

    def test_content_addressing_deduplicates_the_same_public_image(self):
        seed = knowledge_evidence.search_result_evidence_seed(
            self._search_result(), accepted_only=True
        )
        first = knowledge_evidence.finalize_bundle(
            "knowledge_one", seed, data_dir=str(self.data_dir)
        )
        second = knowledge_evidence.finalize_bundle(
            "knowledge_two", seed, data_dir=str(self.data_dir)
        )
        first_asset = next(
            value for value in first["records"]
            if value["modality"] == "IMAGE"
        )["asset_ids"][0]
        second_asset = next(
            value for value in second["records"]
            if value["modality"] == "IMAGE"
        )["asset_ids"][0]
        self.assertEqual(first_asset, second_asset)
        index = knowledge_evidence.load_media_index(str(self.data_dir))
        self.assertEqual(len(index["assets"]), 1)

    def test_parallel_public_assets_do_not_lose_index_entries(self):
        original = base64.b64decode(PNG_BASE64)
        payloads = [
            base64.b64encode(original + bytes([index])).decode("ascii")
            for index in range(8)
        ]

        def store(payload):
            return knowledge_evidence.store_public_images(
                self._source(),
                [payload],
                ["并行公开图片"],
                [1],
                data_dir=str(self.data_dir),
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(store, payloads))
        self.assertTrue(all(len(value) == 1 for value in results))
        index = knowledge_evidence.load_media_index(str(self.data_dir))
        self.assertEqual(len(index["assets"]), 8)

    def test_audit_detects_media_tampering(self):
        _, item = knowledge.apply_verified_fact_lookup_partitioned_claim(
            "请查四禧丸子的官方造型",
            "四禧丸子的角色造型融入国风元素。",
            self._candidate(),
            self._search_result(),
        )
        clean = knowledge.audit_knowledge_evidence()
        self.assertEqual(clean["failures"], [])
        self.assertEqual(clean["counts"]["image_claims"], 1)
        detail = knowledge.load_knowledge_evidence(
            item["id"], include_asset_paths=True
        )
        Path(detail["assets"][0]["resolved_path"]).write_bytes(b"tampered")
        audited = knowledge.audit_knowledge_evidence()
        self.assertTrue(
            any("file_hash_invalid" in value for value in audited["failures"])
        )

    def test_legacy_claims_remain_compatible_and_keep_old_fingerprint(self):
        item = {
            "id": "knowledge_legacy",
            "subject": "Legacy",
            "claim": "A pre-upgrade verified fact.",
            "knowledge_type": "stable",
            "expires_at": None,
            "verification_status": "DOUBLE_CERTIFIED_MULTI_SOURCE",
            "sources": [{"url": "https://example.com/legacy"}],
            "temporal_scope": {},
            "status": "verified",
        }
        old_fields = {
            "id": item.get("id"),
            "subject": item.get("subject"),
            "claim": item.get("claim"),
            "knowledge_type": item.get("knowledge_type"),
            "expires_at": item.get("expires_at"),
            "verification_status": item.get("verification_status"),
            "sources": item.get("sources"),
            "temporal_scope": knowledge.normalize_temporal_scope(
                item.get("temporal_scope")
            ),
            "display_version": knowledge.KNOWLEDGE_DISPLAY_VERSION,
        }
        expected = hashlib.sha256(
            json.dumps(
                old_fields,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(knowledge._curation_fingerprint(item), expected)
        audited = knowledge_evidence.audit_evidence_store(
            [item],
            data_dir=str(self.data_dir),
            media_index=knowledge_evidence.load_media_index(
                str(self.data_dir)
            ),
        )
        self.assertEqual(audited["failures"], [])
        self.assertEqual(audited["counts"]["legacy_compatible"], 1)

    def test_first_start_adds_media_index_without_rewriting_legacy_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            data_dir.mkdir(parents=True)
            legacy = [{
                "id": "knowledge_before_evidence",
                "subject": "Legacy subject",
                "claim": "Legacy claim remains byte-for-byte authoritative.",
                "knowledge_type": "stable",
                "status": "verified",
                "verification_status": "DOUBLE_CERTIFIED_MULTI_SOURCE",
                "sources": [{"url": "https://example.com/legacy"}],
            }]
            (data_dir / "knowledge.json").write_text(
                json.dumps(legacy, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            with patch.multiple(
                knowledge,
                DATA_DIR=str(data_dir),
                KNOWLEDGE_FILE=str(data_dir / "knowledge.json"),
                SOURCES_FILE=str(data_dir / "knowledge_sources.json"),
                LOGS_FILE=str(data_dir / "learning_logs.json"),
                PENDING_SOURCES_FILE=str(
                    data_dir / "knowledge_source_candidates.json"
                ),
            ):
                knowledge.initialize()
            connection = sqlite3.connect(data_dir / "bekki.sqlite3")
            try:
                stored = json.loads(connection.execute(
                    "SELECT payload FROM json_documents "
                    "WHERE namespace='knowledge' AND document_key='knowledge.json'"
                ).fetchone()[0])
                media = json.loads(connection.execute(
                    "SELECT payload FROM json_documents WHERE namespace='knowledge' "
                    "AND document_key='knowledge/media/index.json'"
                ).fetchone()[0])
            finally:
                connection.close()
            self.assertEqual(stored, legacy)
            self.assertEqual(media["schema_version"], 1)
            self.assertEqual(media["assets"], {})

    def test_root_and_casper_evidence_runtime_are_mirrored(self):
        pairs = [
            ("knowledge.py", "casper/knowledge.py"),
            ("knowledge_ai.py", "casper/knowledge_ai.py"),
            ("knowledge_evidence.py", "casper/knowledge_evidence.py"),
            ("knowledge_retrieval.py", "casper/knowledge_retrieval.py"),
            ("knowledge_worker.py", "casper/knowledge_worker.py"),
            ("tools.py", "casper/tools.py"),
            ("prompts/extract_single.txt", "casper/prompts/extract_single.txt"),
            ("prompts/knowledge_extract.txt", "casper/prompts/knowledge_extract.txt"),
            ("prompts/knowledge_judge.txt", "casper/prompts/knowledge_judge.txt"),
            (
                "prompts/knowledge_judge_recover.txt",
                "casper/prompts/knowledge_judge_recover.txt",
            ),
            (
                "prompts/nerv_daily_knowledge_curator.txt",
                "casper/prompts/nerv_daily_knowledge_curator.txt",
            ),
            (
                "prompts/nerv_daily_knowledge_curator_recovery.txt",
                "casper/prompts/nerv_daily_knowledge_curator_recovery.txt",
            ),
        ]
        for left, right in pairs:
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    (ROOT / left).read_bytes(),
                    (ROOT / right).read_bytes(),
                )

    def test_build_and_companion_watch_boundaries(self):
        self.assertIn(BUILD_ID, (ROOT / "main.py").read_text("utf-8"))
        metadata = json.loads((ROOT / "BEKKI_BUILD.json").read_text("utf-8"))
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(
            hashlib.sha256(
                (ROOT / "companion_watch.py").read_bytes()
            ).hexdigest(),
            "3100cee054946f482cc1a086ece959e4c2d3020d1713afd7d58124759ed4c4a5",
        )


if __name__ == "__main__":
    unittest.main()
