import ast
from pathlib import Path
import tempfile
import unittest

from nerv.curiosity import CuriosityJournal


ROOT = Path(__file__).resolve().parents[1]


class ResponsiveConversationWidthV110415Tests(unittest.TestCase):
    @staticmethod
    def _ui_width_contract():
        tree = ast.parse((ROOT / "ui.py").read_text(encoding="utf-8"))
        names = {
            "MESSAGE_CONTENT_WIDTH",
            "MESSAGE_CONTENT_MAX_WIDTH",
            "MESSAGE_RESPONSIVE_WIDTH_RATIO",
            "RESULT_CARD_WIDTH_OFFSET",
        }
        nodes = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in names
                for target in node.targets
            ):
                nodes.append(node)
            elif isinstance(node, ast.FunctionDef) and node.name in {
                "_responsive_message_content_width",
                "_result_card_width",
            }:
                nodes.append(node)
        namespace = {}
        exec(compile(ast.fix_missing_locations(ast.Module(nodes, [])), "ui.py", "exec"), namespace)
        return namespace

    def test_width_curve_keeps_small_window_and_expands_maximized_window(self):
        contract = self._ui_width_contract()
        responsive_width = contract["_responsive_message_content_width"]
        self.assertEqual(responsive_width(480), 350)
        self.assertEqual(responsive_width(1000), 720)
        self.assertEqual(responsive_width(1800), 760)

    def test_assistant_bubble_card_context_and_graph_reflow_together(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("self.bubble.setMaximumWidth(content_width)", source)
        self.assertIn("self.result_cards.set_content_width(content_width)", source)
        self.assertIn("self.source_cards.set_content_width(content_width)", source)
        self.assertIn("self.context_label.setFixedWidth(content_width)", source)
        self.assertIn("image.set_display_width(content_width)", source)
        contract = self._ui_width_contract()
        self.assertEqual(contract["_result_card_width"](760), 770)
        self.assertEqual(contract["_result_card_width"](350), 360)

    def test_short_user_message_remains_compact_on_wide_window(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("dynamic_width=self._is_user_message", source)
        self.assertIn("maximum_width=self._content_width", source)

    def test_chat_area_owns_resize_driven_message_reflow(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("def _apply_responsive_message_widths(self):", source)
        self.assertIn("widget.set_available_width(viewport_width)", source)
        self.assertEqual(
            (ROOT / "ui.py").read_bytes(),
            (ROOT / "casper" / "ui.py").read_bytes(),
        )


class CuriosityWriterRecoveryV110415Tests(unittest.TestCase):
    @staticmethod
    def _proposal():
        return {
            "proposal": {
                "question": "卡黄这一称呼最早源于哪些公开互动或事件？",
                "reason": "刚才的内容留下了称呼来源这一背景问题。",
                "trigger_summary": "公开人物关系称呼的由来。",
                "interest_score": 0.84,
                "confidence": 0.82,
                "sharing_risk": "NORMAL",
                "topic_stage": "NEW_OR_SPARSE",
                "current_turn_depth": "FOUNDATION",
                "question_depth": "FOUNDATION",
                "foundation_facet": "EVENTS_OR_STORIES",
                "breadth_relation": "DISTINCT_FOUNDATION_FACET",
                "breadth_fit": True,
                "related_curiosity_ids": [],
                "related_knowledge_ids": [],
                "depth_fit": True,
            }
        }

    def test_truncated_writer_output_retries_instead_of_reporting_no_curiosity(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        responses = [None, self._proposal()]
        budgets = []

        def model_call(*_args, **kwargs):
            budgets.append(kwargs.get("num_predict"))
            return responses.pop(0)

        journal = CuriosityJournal(
            model_call=model_call,
            unload_model=lambda _name: None,
            base_dir=Path(temporary.name),
        )
        result = journal.observe_turn(
            "李艺彤和黄婷婷是什么关系？",
            "公开内容把两人称为卡黄。",
            "SOCIAL_RESEARCH",
        )

        self.assertEqual(result["status"], "drafted")
        self.assertEqual(budgets, [1200, 1600])

    def test_two_invalid_outputs_have_an_honest_diagnostic_reason(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        responses = [None, None]

        def model_call(*_args, **_kwargs):
            return responses.pop(0)

        journal = CuriosityJournal(
            model_call=model_call,
            unload_model=lambda _name: None,
            base_dir=Path(temporary.name),
        )
        result = journal.observe_turn("公开话题", "已查到资料。", "FACT_LOOKUP")
        self.assertEqual(result, {
            "status": "ignored",
            "reason": "writer_invalid_output",
        })


if __name__ == "__main__":
    unittest.main()
