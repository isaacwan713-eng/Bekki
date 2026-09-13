import ast
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import unittest

import localization
import social_video


ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = (ROOT / "ui.py").read_text(encoding="utf-8")


def result_card_method(name):
    tree = ast.parse(UI_SOURCE)
    result_card = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ResultCard"
    )
    method = next(
        node
        for node in result_card.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    namespace = {}
    exec(
        compile(ast.Module(body=[method], type_ignores=[]), "ui.py", "exec"),
        namespace,
    )
    return namespace[name]


class FakeCoreWebView:
    def __init__(self):
        self.IsMuted = True
        self.IsDocumentPlayingAudio = True


class FakeAudioCard:
    def __init__(self):
        self._video_core = FakeCoreWebView()
        self._video_active = True
        self._video_contract = {"platform": "bilibili"}


class InlineSocialVideoAudioFullscreenV11045Tests(unittest.TestCase):
    def test_bilibili_contract_requests_unmuted_audio_after_user_play(self):
        contract = social_video.social_video_contract(
            "https://www.bilibili.com/video/BV1Km66YvEDc"
        )
        query = parse_qs(urlparse(contract["embed_url"]).query)
        self.assertEqual(query["autoplay"], ["1"])
        self.assertEqual(query["muted"], ["0"])

    def test_webview_audio_guard_functionally_clears_global_mute(self):
        card = FakeAudioCard()
        result_card_method("_ensure_inline_video_audio")(card, "test")
        self.assertFalse(card._video_core.IsMuted)

    def test_audio_events_are_observed_reasserted_and_detached(self):
        self.assertIn("core_webview.IsMuted = False", UI_SOURCE)
        self.assertIn("core_webview.IsMutedChanged += audio_state_changed", UI_SOURCE)
        self.assertIn(
            "core_webview.IsDocumentPlayingAudioChanged += audio_state_changed",
            UI_SOURCE,
        )
        self.assertIn("core_webview.IsMutedChanged -= handler", UI_SOURCE)
        self.assertIn(
            "core_webview.IsDocumentPlayingAudioChanged -= handler",
            UI_SOURCE,
        )
        self.assertIn(
            'QTimer.singleShot(250, lambda: enable_audio("player_loaded_250ms"))',
            UI_SOURCE,
        )
        self.assertIn(
            'QTimer.singleShot(1000, lambda: enable_audio("player_loaded_1000ms"))',
            UI_SOURCE,
        )
        self.assertIn("[INLINE VIDEO AUDIO]", UI_SOURCE)

    def test_bekki_has_button_f11_and_escape_fullscreen_controls(self):
        self.assertIn('self.fullscreen_button = QPushButton("⛶")', UI_SOURCE)
        self.assertIn('QKeySequence("F11")', UI_SOURCE)
        self.assertIn('QKeySequence("Esc")', UI_SOURCE)
        self.assertIn("self.showFullScreen()", UI_SOURCE)
        self.assertIn("self.showMaximized()", UI_SOURCE)
        self.assertIn("self.showNormal()", UI_SOURCE)
        self.assertIn("event.type() == QEvent.WindowStateChange", UI_SOURCE)
        self.assertGreaterEqual(
            UI_SOURCE.count(
                "if not self.isFullScreen() and not self.isMaximized():"
            ),
            4,
        )

    def test_fullscreen_tooltips_exist_for_every_supported_language(self):
        for language in localization.SUPPORTED_LANGUAGES:
            with self.subTest(language=language):
                self.assertTrue(localization.TEXT[language]["fullscreen_enter"])
                self.assertTrue(localization.TEXT[language]["fullscreen_exit"])

    def test_build_and_runtime_mirrors_are_current(self):
        build_id = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"
        metadata = json.loads((ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["build_id"], build_id)
        self.assertIn(
            f'BEKKI_BUILD_ID = "{build_id}"',
            (ROOT / "main.py").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            (ROOT / "ui.py").read_bytes(),
            (ROOT / "casper" / "ui.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "social_video.py").read_bytes(),
            (ROOT / "casper" / "social_video.py").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
