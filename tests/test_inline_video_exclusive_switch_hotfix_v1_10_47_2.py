import ast
from pathlib import Path
import weakref
import unittest


ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = (ROOT / "ui.py").read_text(encoding="utf-8")


def top_level_function(name):
    tree = ast.parse(UI_SOURCE)
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    return ast.get_source_segment(UI_SOURCE, node)


def class_method(class_name, method_name):
    tree = ast.parse(UI_SOURCE)
    class_node = next(
        item
        for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == class_name
    )
    node = next(
        item
        for item in class_node.body
        if isinstance(item, ast.FunctionDef) and item.name == method_name
    )
    return ast.get_source_segment(UI_SOURCE, node)


def claim_namespace():
    tree = ast.parse(UI_SOURCE)
    names = {"_qt_object_is_alive", "_claim_active_video_card"}
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
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
    def __init__(self, video_id, stop_succeeds=True):
        self.alive = True
        self._video_contract = {"video_id": video_id}
        self._video_active = True
        self.stop_calls = 0
        self.stop_succeeds = stop_succeeds

    def _stop_inline_video(self):
        self.stop_calls += 1
        if self.stop_succeeds:
            self._video_active = False


class InlineVideoExclusiveSwitchHotfixV110472Tests(unittest.TestCase):
    def test_second_claim_stops_first_before_becoming_active(self):
        namespace = claim_namespace()
        first = FakeCard("first")
        second = FakeCard("second")
        namespace["_ACTIVE_VIDEO_CARD_REF"] = weakref.ref(first)

        self.assertTrue(namespace["_claim_active_video_card"](second))
        self.assertEqual(first.stop_calls, 1)
        self.assertFalse(first._video_active)
        self.assertIs(namespace["_ACTIVE_VIDEO_CARD_REF"](), second)

    def test_second_claim_is_rejected_if_first_cannot_stop(self):
        namespace = claim_namespace()
        first = FakeCard("first", stop_succeeds=False)
        second = FakeCard("second")
        namespace["_ACTIVE_VIDEO_CARD_REF"] = weakref.ref(first)

        self.assertFalse(namespace["_claim_active_video_card"](second))
        self.assertEqual(first.stop_calls, 1)
        self.assertIs(namespace["_ACTIVE_VIDEO_CARD_REF"](), first)

    def test_native_player_is_muted_and_stopped_before_event_detach(self):
        source = class_method("ResultCard", "_stop_inline_video")
        inactive = source.index("self._video_active = False")
        mute = source.index("core_webview.IsMuted = True")
        stop = source.index("core_webview.Stop()")
        detach = source.index("self._detach_inline_webview_events()")
        self.assertLess(inactive, mute)
        self.assertLess(mute, stop)
        self.assertLess(stop, detach)
        self.assertIn("[INLINE VIDEO STOP]", source)

    def test_late_webview_initialization_is_quarantined(self):
        source = class_method("ResultCard", "_configure_inline_webview")
        self.assertIn("if not self._video_active:", source)
        self.assertIn("core_webview.IsMuted = True", source)
        self.assertIn("core_webview.Stop()", source)
        self.assertIn("stale_initialization_stopped", source)

    def test_theater_switch_destroys_previous_player(self):
        source = class_method("BekkiWindow", "enter_theater_mode")
        self.assertIn("current._stop_inline_video()", source)
        self.assertNotIn("self.exit_theater_mode(current)", source)

    def test_plain_theater_exit_still_preserves_playback(self):
        source = class_method("BekkiWindow", "exit_theater_mode")
        self.assertIn("target._restore_video_host_from_theater()", source)
        self.assertNotIn("target._stop_inline_video", source)

    def test_runtime_mirror_and_build_are_current(self):
        build_id = "bekki-verified-video-site-bridge-hotfix-v1-10-47-3-20260902"
        self.assertIn(
            'BEKKI_BUILD_ID = "' + build_id + '"',
            (ROOT / "main.py").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            (ROOT / "ui.py").read_bytes(),
            (ROOT / "casper" / "ui.py").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
