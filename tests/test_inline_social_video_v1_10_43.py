from pathlib import Path
import unittest

import social_video


ROOT = Path(__file__).resolve().parents[1]


class InlineSocialVideoV11043Tests(unittest.TestCase):
    def test_youtube_short_is_a_vertical_inline_contract(self):
        contract = social_video.social_video_contract(
            "https://www.youtube.com/shorts/CkrvP8IVWSE?feature=share"
        )
        self.assertEqual(contract["platform"], "youtube")
        self.assertEqual(contract["video_id"], "CkrvP8IVWSE")
        self.assertTrue(contract["is_short"])
        self.assertIn("youtube.com/embed/CkrvP8IVWSE", contract["embed_url"])
        self.assertIn("autoplay=1", contract["embed_url"])

    def test_standard_youtube_and_short_link_are_supported(self):
        for value in (
            "https://www.youtube.com/watch?v=abc123XYZ_-&list=PL123",
            "https://youtu.be/abc123XYZ_-?si=tracking",
            "https://www.youtube.com/live/abc123XYZ_-",
        ):
            with self.subTest(value=value):
                contract = social_video.social_video_contract(value)
                self.assertEqual(contract["video_id"], "abc123XYZ_-")
                self.assertFalse(contract["is_short"])

    def test_bilibili_video_has_a_bound_inline_contract(self):
        contract = social_video.social_video_contract(
            "https://www.bilibili.com/video/BV1Km66YvEDc"
        )
        self.assertEqual(contract["platform"], "bilibili")
        self.assertEqual(contract["video_id"], "BV1Km66YvEDc")
        self.assertIn("player.bilibili.com/player.html", contract["embed_url"])
        self.assertIn("autoplay=1", contract["embed_url"])

    def test_channels_searches_playlists_and_malicious_hosts_are_rejected(self):
        for value in (
            "https://www.youtube.com/@aespa/shorts",
            "https://www.youtube.com/results?search_query=aespa",
            "https://www.youtube.com/playlist?list=PL123",
            "https://youtube.com.evil.example/shorts/CkrvP8IVWSE",
            "http://www.youtube.com/shorts/CkrvP8IVWSE",
            "https://user:secret@www.youtube.com/shorts/CkrvP8IVWSE",
            "https://www.bilibili.com/search?keyword=aespa",
            "https://space.bilibili.com/12345",
            "https://www.youtube.com/watch?v=too-short",
            "https://youtu.be/CkrvP8IVWSE/extra",
            "https://www.youtube.com:444/shorts/CkrvP8IVWSE",
        ):
            with self.subTest(value=value):
                self.assertIsNone(social_video.social_video_contract(value))

    def test_main_frame_navigation_cannot_escape_the_bound_player(self):
        contract = social_video.social_video_contract(
            "https://www.youtube.com/shorts/CkrvP8IVWSE"
        )
        self.assertTrue(
            social_video.allowed_webview_navigation(
                social_video.webview_wrapper_url(contract), contract
            )
        )
        self.assertTrue(
            social_video.allowed_webview_navigation(contract["embed_url"], contract)
        )
        self.assertTrue(
            social_video.allowed_webview_navigation("about:blank", contract)
        )
        self.assertFalse(
            social_video.allowed_webview_navigation(
                "https://www.youtube.com/watch?v=CkrvP8IVWSE", contract
            )
        )
        self.assertFalse(
            social_video.allowed_webview_navigation(
                "https://example.com/embed/CkrvP8IVWSE", contract
            )
        )

    def test_ui_contract_is_lazy_inline_paused_and_single_active(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("在 Bekki 播放", source)
        self.assertIn("_start_inline_video", source)
        self.assertIn("_stop_inline_video", source)
        self.assertIn("_claim_active_video_card", source)
        self.assertIn("QtWebView2Widget", source)
        self.assertIn("handle_new_window=False", source)
        self.assertIn("social_video.webview_wsgi_app", source)
        self.assertIn('_safe_qt_call(view, "close")', source)
        self.assertNotIn("QWebEngineView", source)
        self.assertNotIn("QDesktopServices.openUrl(QUrl(self._video_contract", source)

    def test_runtime_ui_mirror_matches(self):
        self.assertEqual(
            (ROOT / "ui.py").read_bytes(),
            (ROOT / "casper" / "ui.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "social_video.py").read_bytes(),
            (ROOT / "casper" / "social_video.py").read_bytes(),
        )

    def test_packaged_build_keeps_webview2_modules(self):
        for relative_path in ("Bekki.spec", "casper/Bekki.spec"):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("collect_all(", source)
            self.assertIn("'qtwebview2'", source)
            self.assertNotIn("PySide6.QtWebEngine", source)


if __name__ == "__main__":
    unittest.main()
