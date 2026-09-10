from pathlib import Path
from urllib.parse import parse_qs, urlparse
import unittest

import social_video


ROOT = Path(__file__).resolve().parents[1]


class InlineSocialVideoCompatHotfixV110431Tests(unittest.TestCase):
    def test_youtube_embed_carries_client_identity_parameters(self):
        contract = social_video.social_video_contract(
            "https://www.youtube.com/shorts/CkrvP8IVWSE"
        )
        parsed = urlparse(contract["embed_url"])
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.hostname, "www.youtube.com")
        self.assertEqual(query["origin"], [social_video.WEBVIEW_WRAPPER_ORIGIN])
        self.assertEqual(
            query["widget_referrer"],
            [social_video.WEBVIEW_WRAPPER_ORIGIN + "/"],
        )

    def test_verified_wrapper_is_referrer_bearing_and_starts_in_place(self):
        contract = social_video.social_video_contract(
            "https://www.youtube.com/shorts/CkrvP8IVWSE"
        )
        wrapper = social_video.embed_wrapper_html(contract)
        self.assertIn('id="bekki-inline-player"', wrapper)
        self.assertIn('referrerpolicy="strict-origin-when-cross-origin"', wrapper)
        self.assertIn("autoplay%3D1", wrapper.replace("=", "%3D"))
        self.assertIn("allowfullscreen", wrapper)
        self.assertEqual(
            social_video.embed_document_url(contract),
            social_video.webview_wrapper_url(contract),
        )

    def test_tampered_contract_never_reaches_the_wrapper(self):
        contract = social_video.social_video_contract(
            "https://www.youtube.com/shorts/CkrvP8IVWSE"
        )
        contract["embed_url"] = "https://evil.example/player"
        self.assertEqual(social_video.embed_wrapper_html(contract), "")
        self.assertEqual(social_video.embed_document_url(contract), "")

    def test_ui_uses_verified_https_wrapper_inside_edge_webview2(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("QtWebView2Widget", source)
        self.assertIn("social_video.webview_start_url", source)
        self.assertIn("social_video.webview_wsgi_app", source)
        self.assertIn('"wsgi_host_name": social_video.WEBVIEW_WRAPPER_HOST', source)
        self.assertNotIn("QWebEngine", source)

    def test_ui_logs_webview2_readiness_instead_of_qt_codec_probe(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("[INLINE VIDEO WEBVIEW2]", source)
        self.assertIn("wrapper_loaded", source)
        self.assertNotIn("[INLINE VIDEO CODECS]", source)

    def test_root_and_runtime_player_sources_match(self):
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
