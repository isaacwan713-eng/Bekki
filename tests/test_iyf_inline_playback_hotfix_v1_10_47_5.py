from pathlib import Path
import unittest

import social_video
from casper import browser as casper_browser


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"


class IYFInlineContractTests(unittest.TestCase):
    def test_show_and_episode_pages_are_direct_playback_contracts(self):
        show_url = "https://www.iyf.tv/play/Ee6i5KLMvDF"
        show = social_video.social_video_contract(show_url)
        episode = social_video.social_video_contract(
            show_url + "?id=b497HRwrzDV"
        )

        self.assertEqual(show["platform"], "iyf")
        self.assertEqual(show["show_id"], "Ee6i5KLMvDF")
        self.assertTrue(show["direct_page"])
        self.assertEqual(social_video.webview_start_url(show), show_url)
        self.assertEqual(social_video.webview_wrapper_url(show), "")
        self.assertIsNone(social_video.webview_wsgi_app(show))
        self.assertEqual(episode["video_id"], "Ee6i5KLMvDF:b497HRwrzDV")

    def test_navigation_is_bounded_to_episodes_of_the_selected_show(self):
        contract = social_video.social_video_contract(
            "https://www.iyf.tv/play/Ee6i5KLMvDF"
        )
        self.assertTrue(
            social_video.allowed_webview_navigation(
                "https://m.iyf.tv/play/Ee6i5KLMvDF?id=b497HRwrzDV",
                contract,
            )
        )
        for value in (
            "https://www.iyf.tv/play/AnotherShow",
            "https://www.iyf.tv/search/名侦探柯南",
            "https://ads.example/video/Ee6i5KLMvDF",
            "http://www.iyf.tv/play/Ee6i5KLMvDF",
            "https://www.iyf.tv/play/Ee6i5KLMvDF?redirect=evil",
        ):
            with self.subTest(value=value):
                self.assertFalse(
                    social_video.allowed_webview_navigation(value, contract)
                )

    def test_non_player_iyf_pages_and_malformed_ids_fail_closed(self):
        for value in (
            "https://www.iyf.tv/",
            "https://www.iyf.tv/search/名侦探柯南",
            "https://iyf.tv.evil.example/play/Ee6i5KLMvDF",
            "https://www.iyf.tv/play/x",
            "https://www.iyf.tv/play/Ee6i5KLMvDF?id=bad/value",
            "https://www.iyf.tv/play/Ee6i5KLMvDF#escape",
        ):
            with self.subTest(value=value):
                self.assertIsNone(social_video.social_video_contract(value))


class IYFSelectionAndUIContractTests(unittest.TestCase):
    def test_exact_show_title_outranks_related_conan_titles(self):
        plan = {
            "topic": "名侦探柯南",
            "selection_mode": "EXACT",
            "requested_sites": ["iyf.tv"],
        }
        exact = casper_browser._score_media_watch_candidate(
            {
                "title": "名侦探柯南",
                "description": "更新到1271集",
                "url": "https://www.iyf.tv/play/Ee6i5KLMvDF",
                "domain": "iyf.tv",
            },
            plan,
        )
        related = casper_browser._score_media_watch_candidate(
            {
                "title": "名侦探柯南：绀碧之棺",
                "description": "剧场版",
                "url": "https://www.iyf.tv/play/AnotherShow",
                "domain": "iyf.tv",
            },
            plan,
        )
        self.assertGreater(exact["watch_score"], related["watch_score"])
        self.assertTrue(exact["inline_playable"])

    def test_direct_pages_receive_only_the_randomized_companion_bridge(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("social_video.webview_start_url", source)
        self.assertIn('"bekki_companion_event_" + secrets.token_hex(12)', source)
        self.assertIn('"js_apis": js_bridge', source)
        self.assertIn("social_video.direct_companion_bootstrap_script", source)
        self.assertIn("view = QtWebView2Widget(**view_options)", source)
        self.assertNotIn("陪看对话暂未接入", source)

    def test_build_and_runtime_mirrors_are_current(self):
        self.assertIn(
            'BEKKI_BUILD_ID = "' + BUILD_ID + '"',
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
