import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import image_loader
import knowledge
import knowledge_ai
import knowledge_evidence
import knowledge_worker
import tools


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"

PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/x8AAusB9Y9Z4QAAAABJRU5ErkJggg=="
)


def source():
    return {
        "name": "四禧丸子官方介绍",
        "title": "四禧丸子官方介绍",
        "url": "https://official.example/characters",
        "domain": "official.example",
        "status": "approved",
        "trust": "official",
        "trust_score": 0.97,
        "topics": ["四禧丸子"],
    }


def extracted_item(modality="TEXT_AND_IMAGE", indexes=None):
    return {
        "subject": "四禧丸子",
        "claim": "四禧丸子的角色造型融入国风元素。",
        "evidence_excerpt": "四禧丸子的角色造型融入国风元素",
        "topics": ["四禧丸子"],
        "published_at": None,
        "knowledge_type": "stable",
        "lifecycle_basis": "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM",
        "suggested_valid_for_days": None,
        "temporal_scope": {},
        "confidence": 0.96,
        "risk": "low",
        "evidence": {
            "modality": modality,
            "image_indexes": [1] if indexes is None else indexes,
            "visual_observation": (
                "官方画面展示四名采用国风服饰元素的角色。"
                if modality == "TEXT_AND_IMAGE" else ""
            ),
        },
    }


class DummyResponse:
    def __init__(self, html):
        self.text = html
        self.content = html.encode("utf-8")
        self.url = "https://official.example/characters"
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def raise_for_status(self):
        return None


class AutonomousVisualEvidenceTests(unittest.TestCase):
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

    def test_html_reader_captures_only_two_source_carried_https_images(self):
        html = (
            "<html><head>"
            '<meta property="og:image" content="https://cdn.example/hero.jpg?token=secret">'
            "</head><body>"
            + ("Official character description. " * 20)
            + '<img src="http://unsafe.example/plain.jpg" alt="plain">'
            + '<img src="https://127.0.0.1/private.jpg" alt="private">'
            + '<img src="https://cdn.example/logo.png" alt="site logo">'
            + '<img src="https://cdn.example/detail.jpg" alt="costume detail">'
            + '<img src="https://cdn.example/third.jpg" alt="third frame">'
            + "</body></html>"
        )
        with (
            patch.object(tools.requests, "get", return_value=DummyResponse(html)),
            patch.object(
                image_loader,
                "_download_image",
                side_effect=[b"first", b"second", b"third"],
            ) as download,
            patch.object(
                tools.social_browser,
                "_normalize_raster_to_jpeg",
                side_effect=lambda value: value,
            ),
            patch.object(
                tools.social_browser,
                "_meaningful_raster_evidence",
                return_value=True,
            ),
            patch.object(
                tools.social_browser,
                "_raster_is_distinct",
                return_value=True,
            ),
        ):
            result = tools.read_page(
                "https://official.example/characters", include_images=True
            )
        self.assertTrue(result["success"])
        self.assertEqual(len(result["page_images"]), 2)
        self.assertEqual(
            result["page_image_urls"],
            [
                "https://cdn.example/hero.jpg",
                "https://cdn.example/detail.jpg",
            ],
        )
        self.assertEqual(download.call_count, 2)
        self.assertNotIn("secret", json.dumps(result))

    def test_read_source_uses_browser_fallback_and_carries_images(self):
        item_source = source()
        with (
            patch.object(
                tools,
                "read_page",
                return_value={
                    "success": False,
                    "reader_type": "browser_needed",
                    "content": "",
                    "error": "javascript",
                },
            ) as primary,
            patch.object(
                tools,
                "read_page_with_browser",
                return_value={
                    "success": True,
                    "reader_type": "browser",
                    "content": "官方资料" * 120,
                    "error": None,
                    "page_images": [PNG_BASE64],
                    "page_image_labels": ["官方角色画面"],
                    "page_image_urls": ["https://cdn.example/frame.png"],
                },
            ) as browser,
        ):
            text = knowledge_worker.read_source(
                item_source, include_images=True
            )
        self.assertTrue(text.startswith("官方资料"))
        self.assertEqual(item_source["_page_images"], [PNG_BASE64])
        primary.assert_called_once_with(
            item_source["url"], include_images=True
        )
        browser.assert_called_once_with(
            item_source["url"], include_images=True
        )

    def test_extractor_sends_vision_and_builds_hash_bound_image_seed(self):
        page = "官方资料写明：四禧丸子的角色造型融入国风元素。"
        with patch.object(
            tools,
            "run_ai_prompt",
            return_value={"items": [extracted_item()]},
        ) as model:
            candidates = knowledge_worker.extract_candidates(
                source(),
                page,
                ["四禧丸子"],
                page_images=[PNG_BASE64],
                page_image_labels=["官方角色画面"],
                page_image_urls=[
                    "https://cdn.example/frame.png?signed=discarded"
                ],
            )
        self.assertEqual(len(candidates), 1)
        records = candidates[0]["_evidence_seed"]["records"]
        self.assertEqual([record["modality"] for record in records], ["TEXT", "IMAGE"])
        self.assertTrue(candidates[0]["_evidence_fingerprint"])
        self.assertEqual(model.call_args.kwargs["images"], [PNG_BASE64])
        self.assertEqual(
            model.call_args.kwargs["json_schema"],
            knowledge_worker._AUTONOMOUS_EXTRACTION_SCHEMA,
        )
        self.assertNotIn(PNG_BASE64, model.call_args.args[1])

        judge_packet = knowledge_ai._knowledge_judge_packet(
            candidates[0],
            source(),
            [],
            "knowledge_candidate",
            candidates[0]["_evidence_fingerprint"],
        )
        self.assertNotIn(PNG_BASE64, judge_packet)
        self.assertIn("SOURCE_BOUND_VISUAL_OBSERVATION", judge_packet)

        bundle = knowledge_evidence.finalize_bundle(
            "knowledge_candidate",
            candidates[0]["_evidence_seed"],
            data_dir=str(self.data_dir),
        )
        image_record = next(
            record for record in bundle["records"]
            if record["modality"] == "IMAGE"
        )
        self.assertEqual(len(image_record["asset_ids"]), 1)
        self.assertNotIn("_image_payloads", json.dumps(bundle))
        index = knowledge_evidence.load_media_index(str(self.data_dir))
        asset = index["assets"][image_record["asset_ids"][0]]
        self.assertEqual(
            asset["source_image_url"], "https://cdn.example/frame.png"
        )

    def test_invalid_selected_image_downgrades_to_literal_text(self):
        page = "官方资料写明：四禧丸子的角色造型融入国风元素。"
        seed = knowledge_evidence.autonomous_evidence_seed(
            source(),
            page,
            extracted_item(indexes=[2]),
            [PNG_BASE64],
            ["官方角色画面"],
            ["https://cdn.example/frame.png"],
        )
        self.assertEqual(
            [record["modality"] for record in seed["records"]], ["TEXT"]
        )

    def test_user_or_local_media_cannot_enter_autonomous_seed(self):
        private_source = source()
        private_source.update({
            "user_supplied": True,
            "source_origin": "USER_UPLOAD",
            "privacy_class": "PRIVATE_MEDIA",
        })
        seed = knowledge_evidence.autonomous_evidence_seed(
            private_source,
            "四禧丸子的角色造型融入国风元素。",
            extracted_item(),
            [PNG_BASE64],
            ["用户图片"],
            ["https://cdn.example/user.png"],
        )
        self.assertIsNone(seed)
        self.assertEqual(
            knowledge_evidence.load_media_index(str(self.data_dir))["assets"],
            {},
        )

    def test_learning_cycle_persists_visual_evidence_and_logs_counts(self):
        item_source = source()

        def read(candidate_source, *, include_images=False):
            self.assertTrue(include_images)
            candidate_source["_page_images"] = [PNG_BASE64]
            candidate_source["_page_image_labels"] = ["官方角色画面"]
            candidate_source["_page_image_urls"] = [
                "https://cdn.example/frame.png"
            ]
            return "官方资料写明：四禧丸子的角色造型融入国风元素。"

        def judge(candidate, _source):
            return {
                "candidate_fingerprint": knowledge.make_id(
                    candidate["subject"], candidate["claim"], {}
                ),
                "evidence_fingerprint": candidate["_evidence_fingerprint"],
                "action": "AUTO_SAVE",
                "target_id": None,
                "knowledge_type": "stable",
                "lifecycle_basis": (
                    "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
                ),
                "valid_for_days": None,
                "temporal_scope": {},
                "confidence": 0.96,
                "risk": "low",
                "reason": "Official text and selected image support the claim.",
                "_judge_output_status": "PRIMARY_VALID",
                "_judge_contract_version": 2,
            }

        with (
            patch.object(knowledge_worker, "choose_sources", return_value=[item_source]),
            patch.object(
                knowledge_worker,
                "review_source_candidates",
                return_value={
                    "approved": 0, "pending": 0, "rejected": 0, "errors": 0,
                },
            ),
            patch.object(knowledge_worker, "read_source", side_effect=read),
            patch.object(
                tools,
                "run_ai_prompt",
                return_value={"items": [extracted_item()]},
            ),
            patch.object(knowledge_ai, "judge_knowledge", side_effect=judge),
            patch.object(
                knowledge_worker,
                "organize_learned_knowledge",
                return_value={"status": "SKIPPED"},
            ),
        ):
            log = knowledge_worker.run_learning_cycle(
                topics=["四禧丸子"], trigger="unit_test"
            )

        self.assertEqual(log["status"], "COMPLETED")
        self.assertEqual(log["visual_evidence"]["source_images_captured"], 1)
        self.assertEqual(log["visual_evidence"]["candidates_with_images"], 1)
        self.assertEqual(
            log["visual_evidence"]["claims_with_persisted_images"], 1
        )
        saved = knowledge.load_items()
        self.assertEqual(len(saved), 1)
        serialized = json.dumps(saved[0], ensure_ascii=False)
        self.assertNotIn(PNG_BASE64, serialized)
        self.assertTrue(any(
            record.get("asset_ids")
            for record in saved[0]["evidence_bundle"]["records"]
            if record.get("modality") == "IMAGE"
        ))
        self.assertNotIn("_page_images", item_source)


class AutonomousVisualEvidenceBuildTests(unittest.TestCase):
    def test_build_metadata_and_mirrors(self):
        metadata = json.loads((ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(
            metadata["update_kind"],
            "Knowledge Visual Recall V1.10.54.7",
        )
        self.assertEqual(
            metadata["parent_build"],
            "Knowledge Autonomous Visual Evidence V1.10.54.6",
        )
        self.assertIn(
            BUILD_ID, (ROOT / "main.py").read_text(encoding="utf-8")
        )
        for relative in (
            "README.md",
            "INSTALL.txt",
            "KNOWLEDGE_AUTONOMOUS_VISUAL_EVIDENCE_V1_10_54_6_NOTES.md",
            "TEST_KNOWLEDGE_AUTONOMOUS_VISUAL_EVIDENCE_V1_10_54_6.ps1",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("V1.10.54.6", text, relative)
        for relative in (
            "knowledge_evidence.py",
            "knowledge_worker.py",
            "tools.py",
            "prompts/knowledge_extract.txt",
        ):
            self.assertEqual(
                (ROOT / relative).read_bytes(),
                (ROOT / "casper" / relative).read_bytes(),
                relative,
            )


if __name__ == "__main__":
    unittest.main()
