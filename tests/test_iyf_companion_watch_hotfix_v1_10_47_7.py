from pathlib import Path
import json
import unittest

import social_video


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


class IYFCompanionScriptTests(unittest.TestCase):
    def setUp(self):
        self.contract = social_video.social_video_contract(
            "https://www.iyf.tv/play/Ee6i5KLMvDF"
        )
        self.bridge_name = "bekki_companion_event_" + ("a" * 24)

    def test_verified_iyf_page_gets_isolated_typed_companion_surface(self):
        script = social_video.direct_companion_bootstrap_script(
            self.contract,
            self.bridge_name,
        )

        self.assertIn('const rootId = "bekki-direct-companion-root"', script)
        self.assertIn('attachShadow({mode:"closed"})', script)
        self.assertIn(json.dumps(self.bridge_name), script)
        self.assertIn("api[bridgeMethod](payload)", script)
        self.assertIn('type:"companion_message"', script)
        self.assertIn('type:"companion_close"', script)
        self.assertIn("input.maxLength = 320", script)
        self.assertIn("item.textContent = text", script)
        self.assertNotIn("window.chrome.webview.postMessage", script)
        self.assertNotIn("https://www.iyf.tv", script)

    def test_unverified_bridge_names_and_non_direct_players_fail_closed(self):
        for bridge_name in (
            "bekki_companion_event",
            "bekki_companion_event_short",
            "bekki_companion_event_" + ("g" * 24),
            "bekki_companion_event_" + ("a" * 24) + "_extra",
        ):
            with self.subTest(bridge_name=bridge_name):
                self.assertEqual(
                    social_video.direct_companion_bootstrap_script(
                        self.contract,
                        bridge_name,
                    ),
                    "",
                )
        youtube = social_video.social_video_contract(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        self.assertEqual(
            social_video.direct_companion_bootstrap_script(
                youtube,
                self.bridge_name,
            ),
            "",
        )


class IYFCompanionRuntimeContractTests(unittest.TestCase):
    def test_direct_player_uses_rpc_and_is_no_longer_disabled(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")

        self.assertIn("js_bridge = DictJsBridge()", source)
        self.assertIn('"bekki_companion_event_" + secrets.token_hex(12)', source)
        self.assertIn(
            "js_bridge.bind_js_api_func(\n"
            "                bekki_companion_event,\n"
            "                name=bridge_name,",
            source,
        )
        self.assertIn('"js_apis": js_bridge', source)
        self.assertIn("social_video.direct_companion_bootstrap_script", source)
        self.assertIn("companion_available = bool(card._video_companion_bridge_name)", source)
        self.assertNotIn(
            'or bool((card._video_contract or {}).get("direct_page"))',
            source,
        )
        self.assertIn("[COMPANION WATCH DIRECT BRIDGE]", source)

    def test_current_build_and_mirrors_are_exact(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertIn(
            f'BEKKI_BUILD_ID = "{BUILD_ID}"',
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
