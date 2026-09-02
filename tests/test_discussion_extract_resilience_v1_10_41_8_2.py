import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tools
from casper import browser as casper_browser
from nerv.curiosity import CuriosityJournal


ROOT = Path(__file__).resolve().parents[1]


def _item(index, *, relevant=True):
    return {
        "index": index,
        "is_relevant": relevant,
        "source_kind": "FORUM_THREAD",
        "discussion_title": f"讨论 {index}",
        "summary": f"来源 {index} 提出一种解释。",
        "claims": [f"来源 {index} 的说法。"],
        "evidence_quote": "",
        "stance": "EXPLAINS_CONTEXT",
        "perspective_key": f"theme_{index}",
        "published_at": "",
        "uncertainty": "该说法未独立证实。",
        "relevance_score": 80,
        "reason": "直接回应问题。",
    }


def _source(index):
    return {
        "title": f"讨论 {index}",
        "description": f"搜索摘要 {index}",
        "domain": "example.com",
        "url": f"https://example.com/{index}",
        "published": "",
        "discussion_source_kind": "FORUM_THREAD",
        "page_success": True,
        "page_content": f"正文 {index}",
        "image_url": "",
    }


def _curiosity_proposal(question):
    return {
        "proposal": {
            "question": question,
            "reason": "想继续了解这个公开话题。",
            "trigger_summary": "公开人物关系讨论。",
            "interest_score": 0.8,
            "confidence": 0.9,
            "sharing_risk": "NORMAL",
            "topic_stage": "NEW_OR_SPARSE",
            "current_turn_depth": "FOUNDATION",
            "question_depth": "FOUNDATION",
            "foundation_facet": "RELATIONSHIPS_OR_CULTURE",
            "breadth_relation": "DISTINCT_FOUNDATION_FACET",
            "breadth_fit": True,
            "related_curiosity_ids": [],
            "related_knowledge_ids": [],
            "depth_fit": True,
        }
    }


class DiscussionExtractResilienceV1104182Tests(unittest.TestCase):
    def test_truncated_array_keeps_every_fully_closed_item(self):
        raw = (
            '{"items":['
            + json.dumps(_item(1), ensure_ascii=False)
            + ','
            + json.dumps(_item(2), ensure_ascii=False)
            + ',{"index":3,"is_relevant":true,"summary":"截断'
        )
        recovered = casper_browser._recover_complete_discussion_payload(raw)
        self.assertEqual(
            [value["index"] for value in recovered["items"]],
            [1, 2],
        )
        self.assertIs(recovered["_partial_json_recovery"], True)

    def test_run_ai_prompt_delegates_invalid_json_to_structural_recovery(self):
        raw = (
            '{"items":['
            + json.dumps(_item(1), ensure_ascii=False)
            + ',{"index":2,"summary":"截断'
        )
        with patch.object(tools, "call_model", return_value=raw):
            recovered = tools.run_ai_prompt(
                "prompts/casper_discussion_extract.txt",
                "{}",
                expect_json=True,
                invalid_json_handler=(
                    casper_browser._recover_complete_discussion_payload
                ),
            )
        self.assertEqual(len(recovered["items"]), 1)
        self.assertEqual(recovered["items"][0]["index"], 1)

    def test_extraction_batches_two_sources_and_retries_only_missing_index(self):
        responses = [
            {"items": [_item(1)], "_partial_json_recovery": True},
            {"items": [_item(2)]},
            {"items": [_item(3)]},
        ]
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=responses,
        ) as model:
            extracted = casper_browser._extract_discussion_sources(
                "卡黄是闹翻了吗，她们为什么会闹翻？",
                [_source(1), _source(2), _source(3)],
            )
        self.assertEqual(
            {value["source_index"] for value in extracted},
            {1, 2, 3},
        )
        self.assertEqual(model.call_count, 3)
        first_packet = json.loads(model.call_args_list[0].args[1])
        retry_packet = json.loads(model.call_args_list[1].args[1])
        self.assertEqual(
            [value["index"] for value in first_packet["sources"]],
            [1, 2],
        )
        self.assertEqual(
            [value["index"] for value in retry_packet["sources"]],
            [2],
        )
        self.assertTrue(callable(
            model.call_args_list[0].kwargs["invalid_json_handler"]
        ))

    def test_one_failed_source_does_not_erase_other_batches(self):
        responses = [
            RuntimeError("first batch failed"),
            {"items": [_item(1)]},
            None,
            {"items": [_item(3), _item(4)]},
        ]
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=responses,
        ):
            extracted = casper_browser._extract_discussion_sources(
                "为什么会这样？",
                [_source(1), _source(2), _source(3), _source(4)],
            )
        self.assertEqual(
            {value["source_index"] for value in extracted},
            {1, 3, 4},
        )

    def test_compound_ship_nickname_cannot_be_split_into_two_terms(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        journal = CuriosityJournal(
            model_call=lambda *_args, **_kwargs: _curiosity_proposal(
                "“卡黄”这两个词分别指代哪些人物或群体？"
            ),
            unload_model=lambda _name: None,
            base_dir=Path(temporary.name),
        )
        result = journal.observe_turn(
            "卡黄是闹翻了吗，她们为什么会闹翻？",
            "这次没有形成可用总结。",
            "DISCUSSION_FEED",
        )
        self.assertEqual(result["status"], "dismissed")
        self.assertIn("compound_label_split", result["reason"])

    def test_grounded_pair_identity_cannot_be_asked_again(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        journal = CuriosityJournal(
            model_call=lambda *_args, **_kwargs: _curiosity_proposal(
                "“卡黄”具体指代哪些人物？"
            ),
            unload_model=lambda _name: None,
            base_dir=Path(temporary.name),
        )
        result = journal.observe_turn(
            "卡黄是闹翻了吗，她们为什么会闹翻？",
            "可读来源中，“卡黄”指的是李艺彤与黄婷婷。",
            "DISCUSSION_FEED",
        )
        self.assertEqual(result["status"], "dismissed")
        self.assertIn("grounded_identity_reask", result["reason"])

    def test_prompts_require_small_batches_and_grounded_pair_identity(self):
        extract = (ROOT / "prompts/casper_discussion_extract.txt").read_text(
            encoding="utf-8"
        )
        synthesis = (
            ROOT / "prompts/casper_discussion_synthesis.txt"
        ).read_text(encoding="utf-8")
        curiosity = (
            ROOT / "prompts/nerv_curiosity_writer_recover.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("batches of at most two", extract)
        self.assertIn("most three short items", extract)
        self.assertIn("name those people once", synthesis)
        self.assertIn("two-character ship nickname", curiosity)


if __name__ == "__main__":
    unittest.main()
