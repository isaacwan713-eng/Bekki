import ast
from pathlib import Path
import weakref
import unittest


ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = (ROOT / "ui.py").read_text(encoding="utf-8")


def lifecycle_namespace():
    tree = ast.parse(UI_SOURCE)
    names = {
        "_qt_object_is_alive",
        "_safe_qt_call",
        "_claim_active_video_card",
        "_release_active_video_card",
        "_release_active_video_card_ref",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]

    class FakeShiboken:
        @staticmethod
        def isValid(value):
            return bool(getattr(value, "alive", False))

    namespace = {
        "shiboken6": FakeShiboken,
        "weakref": weakref,
        "_ACTIVE_VIDEO_CARD_REF": None,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "ui.py", "exec"), namespace)
    return namespace


class FakeCard:
    def __init__(self, alive=True):
        self.alive = alive
        self.stop_calls = 0

    def _stop_inline_video(self):
        self.stop_calls += 1


class FakeWidget:
    def __init__(self, alive=True, raises=False):
        self.alive = alive
        self.raises = raises
        self.calls = []

    def setVisible(self, value):
        if self.raises:
            raise RuntimeError("C++ object already deleted")
        self.calls.append(value)


class InlineVideoLifecycleHotfixV110441Tests(unittest.TestCase):
    def test_invalid_previous_card_is_released_without_stop_call(self):
        namespace = lifecycle_namespace()
        previous = FakeCard(alive=False)
        current = FakeCard(alive=True)
        namespace["_ACTIVE_VIDEO_CARD_REF"] = weakref.ref(previous)

        self.assertTrue(namespace["_claim_active_video_card"](current))
        self.assertEqual(previous.stop_calls, 0)
        self.assertIs(namespace["_ACTIVE_VIDEO_CARD_REF"](), current)

    def test_live_previous_card_is_stopped_before_new_claim(self):
        namespace = lifecycle_namespace()
        previous = FakeCard(alive=True)
        current = FakeCard(alive=True)
        self.assertTrue(namespace["_claim_active_video_card"](previous))

        self.assertTrue(namespace["_claim_active_video_card"](current))
        self.assertEqual(previous.stop_calls, 1)
        self.assertIs(namespace["_ACTIVE_VIDEO_CARD_REF"](), current)

    def test_safe_qt_call_is_idempotent_for_dead_or_raising_widgets(self):
        namespace = lifecycle_namespace()
        dead = FakeWidget(alive=False)
        raising = FakeWidget(alive=True, raises=True)
        live = FakeWidget(alive=True)

        self.assertFalse(namespace["_safe_qt_call"](dead, "setVisible", False))
        self.assertFalse(namespace["_safe_qt_call"](raising, "setVisible", False))
        self.assertTrue(namespace["_safe_qt_call"](live, "setVisible", False))
        self.assertEqual(live.calls, [False])

    def test_destroyed_or_invalid_active_reference_is_clearable(self):
        namespace = lifecycle_namespace()
        active = FakeCard(alive=True)
        active_ref = weakref.ref(active)
        namespace["_ACTIVE_VIDEO_CARD_REF"] = active_ref
        namespace["_release_active_video_card_ref"](active_ref)
        self.assertIsNone(namespace["_ACTIVE_VIDEO_CARD_REF"])

        invalid = FakeCard(alive=False)
        namespace["_ACTIVE_VIDEO_CARD_REF"] = weakref.ref(invalid)
        namespace["_release_active_video_card_ref"](weakref.ref(FakeCard()))
        self.assertIsNone(namespace["_ACTIVE_VIDEO_CARD_REF"])

    def test_result_card_cleanup_uses_validated_calls_and_destroyed_hook(self):
        tree = ast.parse(UI_SOURCE)
        result_card = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ResultCard"
        )
        stop_method = next(
            node
            for node in result_card.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_stop_inline_video"
        )
        stop_source = ast.unparse(stop_method)
        self.assertIn("import shiboken6", UI_SOURCE)
        self.assertIn("shiboken6.isValid(value)", UI_SOURCE)
        self.assertIn("self.destroyed.connect(", UI_SOURCE)
        self.assertIn("_release_active_video_card_ref(current_ref)", UI_SOURCE)
        self.assertIn(
            '_safe_qt_call(self.video_host_layout, "removeWidget", view)',
            UI_SOURCE,
        )
        self.assertIn('_safe_qt_call(self.video_host, "setVisible", False)', UI_SOURCE)
        self.assertIn('_safe_qt_call(view, "close")', UI_SOURCE)
        self.assertNotIn("self.video_host_layout.removeWidget(view)", stop_source)
        self.assertNotIn("self.video_host.setVisible(False)", stop_source)

    def test_build_and_runtime_mirror_are_current(self):
        main_source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn(
            'BEKKI_BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"',
            main_source,
        )
        self.assertEqual(
            (ROOT / "ui.py").read_bytes(),
            (ROOT / "casper" / "ui.py").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
