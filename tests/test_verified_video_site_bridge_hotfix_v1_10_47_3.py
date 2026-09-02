import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import media_watch
import social_video
import video_sites
from casper import browser as casper_browser


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-verified-video-site-bridge-hotfix-v1-10-47-3-20260902"


def _plan(site="iyf.tv", topic="名侦探柯南"):
    return {
        "topic": topic,
        "selection_mode": "EXACT",
        "content_kind": "SERIES",
        "episode_hint": None,
        "requested_sites": [site],
        "site_scope_explicit": True,
    }


def _iyf_candidate():
    return {
        "title": "名侦探柯南",
        "description": "名侦探柯南 1271集",
        "url": "https://www.iyf.tv/play/Ee6i5KLMvDF",
        "domain": "iyf.tv",
        "image_url": "https://www.iyf.tv/example.jpg",
        "discovery_engine": "iyf.tv_native",
    }


class VerifiedVideoSiteRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.registry = Path(self.temporary.name) / "verified_video_sites.json"

    def tearDown(self):
        self.temporary.cleanup()

    def test_user_wording_never_registers_a_site_without_structural_evidence(self):
        self.assertEqual(
            media_watch.extract_requested_sites("去example.com播放视频"),
            ["example.com"],
        )
        with self.assertRaisesRegex(ValueError, "insufficient_video_site_evidence"):
            video_sites.record_verified_site(
                "example.com",
                {
                    "detail_link_count": 5,
                    "taxonomy_hit_count": 3,
                    "media_element_count": 0,
                },
                path=self.registry,
            )
        self.assertFalse(video_sites.is_verified("example.com", self.registry))

    def test_repeated_catalog_evidence_is_persisted_and_alias_is_reusable(self):
        item = video_sites.record_verified_site(
            "iyf.tv",
            {
                "detail_link_count": 61,
                "taxonomy_hit_count": 5,
                "media_element_count": 0,
            },
            aliases=["爱壹帆"],
            search_url_template="https://www.iyf.tv/search/{query}",
            path=self.registry,
        )
        self.assertTrue(item["verified"])
        self.assertEqual(item["search_url_template"], "https://www.iyf.tv/search/{query}")
        self.assertEqual(video_sites.match_aliases("去爱壹帆看柯南", self.registry), ["iyf.tv"])
        with patch.object(video_sites, "REGISTRY_FILE", self.registry):
            self.assertEqual(
                media_watch.extract_requested_sites("去爱壹帆看名侦探柯南"),
                ["iyf.tv"],
            )
            self.assertEqual(
                media_watch.fallback_topic("去爱壹帆看名侦探柯南", ["iyf.tv"]),
                "名侦探柯南",
            )

    def test_corrupt_persisted_counters_fail_soft(self):
        self.registry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "sites": {
                        "iyf.tv": {
                            "verified": True,
                            "verification_count": "not-a-number",
                            "aliases": "not-a-list",
                            "evidence": ["not-a-dict"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        item = video_sites.get_site("iyf.tv", self.registry)
        self.assertEqual(item["verification_count"], 0)
        self.assertEqual(item["evidence"]["detail_link_count"], 0)

    def test_generic_page_titles_are_not_learned_as_site_aliases(self):
        item = video_sites.record_verified_site(
            "example.tv",
            {
                "detail_link_count": 12,
                "taxonomy_hit_count": 3,
                "media_element_count": 0,
            },
            aliases=["视频", "Watch", "示例影视"],
            path=self.registry,
        )
        self.assertNotIn("视频", item["aliases"])
        self.assertNotIn("watch", item["aliases"])
        self.assertIn("示例影视", item["aliases"])


class VerifiedVideoSiteDiscoveryTests(unittest.TestCase):
    def test_catalog_structure_passes_but_incidental_video_links_do_not(self):
        catalog_links = [
            {"url": "https://www.iyf.tv/play/show-" + str(index), "text": "节目"}
            for index in range(6)
        ]
        verified = casper_browser._video_site_surface_evidence(
            "iyf.tv",
            "电影 电视剧 动漫",
            catalog_links,
        )
        self.assertTrue(verified["verified"])

        forum_links = catalog_links[:5]
        rejected = casper_browser._video_site_surface_evidence(
            "example.com",
            "电影 电视剧 视频",
            [
                {"url": item["url"].replace("iyf.tv", "example.com"), "text": "帖子"}
                for item in forum_links
            ],
        )
        self.assertFalse(rejected["verified"])

    def test_observed_search_url_is_generalized_only_on_the_same_domain(self):
        template = casper_browser._video_site_search_template(
            "https://www.iyf.tv/search/%E5%90%8D%E4%BE%A6%E6%8E%A2%E6%9F%AF%E5%8D%97",
            "名侦探柯南",
            "iyf.tv",
        )
        self.assertEqual(template, "https://www.iyf.tv/search/{query}")
        self.assertEqual(
            casper_browser._video_site_search_template(
                "https://evil.example/search/%E5%90%8D%E4%BE%A6%E6%8E%A2%E6%9F%AF%E5%8D%97",
                "名侦探柯南",
                "iyf.tv",
            ),
            "",
        )

    def test_catalog_converter_keeps_show_page_and_drops_episode_number(self):
        results = casper_browser._video_site_candidates(
            [
                {
                    "url": "https://www.iyf.tv/play/Ee6i5KLMvDF",
                    "text": "名侦探柯南",
                    "image_url": "https://www.iyf.tv/conan.jpg",
                },
                {
                    "url": "https://www.iyf.tv/play/episode-1",
                    "text": "1",
                },
                {"url": "https://www.iyf.tv/help", "text": "帮助"},
            ],
            "iyf.tv",
        )
        self.assertEqual([item["title"] for item in results], ["名侦探柯南"])
        self.assertEqual(results[0]["url"], "https://www.iyf.tv/play/Ee6i5KLMvDF")

    def test_unknown_explicit_site_uses_verifier_route(self):
        expected = [_iyf_candidate()]
        with patch.object(
            casper_browser,
            "_discover_verified_video_site",
            return_value=(expected, ["iyf.tv_native:名侦探柯南"]),
        ) as discover:
            candidates, queries = casper_browser._discover_native_media_watch(_plan())
        self.assertEqual(candidates, expected)
        self.assertEqual(queries, ["iyf.tv_native:名侦探柯南"])
        discover.assert_called_once()


class VerifiedVideoSiteControllerTests(unittest.TestCase):
    def test_unverified_domain_stops_before_general_web_fallback(self):
        with patch.object(
            casper_browser,
            "_discover_native_media_watch",
            return_value=([], ["example.com_native:电影"]),
        ), patch.object(
            video_sites,
            "is_verified",
            return_value=False,
        ), patch.object(
            casper_browser,
            "discover_web",
            side_effect=AssertionError("unverified site must not reach web fallback"),
        ) as web:
            result = casper_browser.media_watch_controller(
                "去example.com播放电影",
                preplanned=_plan("example.com", "电影"),
            )
        self.assertEqual(result["status"], "UNVERIFIED_VIDEO_SITE")
        self.assertIn("没有把它登记为视频网站", result["direct_reply"])
        web.assert_not_called()

    def test_verified_iyf_result_wins_but_remains_honest_link_only(self):
        with patch.object(
            casper_browser,
            "_discover_native_media_watch",
            return_value=([_iyf_candidate()], ["iyf.tv_native:名侦探柯南"]),
        ), patch.object(
            video_sites,
            "is_verified",
            return_value=True,
        ), patch.object(
            casper_browser,
            "discover_web",
            side_effect=AssertionError("relevant native result must win"),
        ) as web:
            result = casper_browser.media_watch_controller(
                "去iyf.tv播放名侦探柯南",
                preplanned=_plan(),
            )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["cards"][0]["url"], _iyf_candidate()["url"])
        self.assertIsNone(result["pending_action"])
        self.assertIn("不能在 Bekki 内嵌播放", result["direct_reply"])
        web.assert_not_called()


class CompanionBridgeContractTests(unittest.TestCase):
    def test_wrapper_uses_qtwebview2_rpc_instead_of_raw_web_messages(self):
        contract = social_video.social_video_contract(
            "https://www.bilibili.com/video/BV1Km66YvEDc"
        )
        document = social_video.embed_wrapper_html(contract)
        self.assertIn("window.qtwebview2 && window.qtwebview2.api", document)
        self.assertIn("api.bekki_companion_event(payload)", document)
        self.assertNotIn("window.chrome.webview.postMessage", document)

    def test_python_bridge_uses_dict_js_bridge_contract(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("from qtwebview2 import DictJsBridge", source)
        self.assertIn("@js_bridge.bind_js_api_func", source)
        self.assertIn("js_apis=js_bridge", source)
        self.assertNotIn("core_webview.WebMessageReceived +=", source)

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
