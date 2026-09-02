from datetime import date
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw

import magi
import melchior
import social_browser
import tools


ROOT = Path(__file__).resolve().parents[1]


def _jpeg(pattern):
    image = Image.new("RGB", (640, 360), (22, 28, 38))
    draw = ImageDraw.Draw(image)
    if pattern == "cover":
        draw.rectangle((30, 30, 610, 330), fill=(215, 45, 65))
        draw.ellipse((180, 65, 460, 330), fill=(40, 115, 225))
    elif pattern == "frame":
        draw.rectangle((20, 20, 620, 340), fill=(35, 170, 105))
        draw.polygon(((80, 310), (330, 40), (580, 310)), fill=(210, 185, 35))
    destination = BytesIO()
    image.save(destination, format="JPEG", quality=86)
    return destination.getvalue()


class _EmptyLocators:
    def count(self):
        return 0


class _MetadataPage:
    def evaluate(self, script, *_args):
        if "ytInitialPlayerResponse" in script:
            return {
                "title": "Current YouTube Video",
                "description": "Only this video's description.",
                "author": "Current Channel",
                "cover": "https://i.ytimg.com/vi/abc123XYZ_-/maxresdefault.jpg",
                "thumbnail_urls": [
                    "https://i.ytimg.com/vi/abc123XYZ_-/maxresdefault.jpg"
                ],
                "published_at": "2026-08-28",
                "video_id": "abc123XYZ_-",
                "is_short": False,
            }
        return []

    def locator(self, _selector):
        return _EmptyLocators()


class YouTubeSocialEvidenceV11042Tests(unittest.TestCase):
    def test_youtube_search_url_preserves_literal_query(self):
        query = "@aespa Shorts live clip abc123XYZ_-"
        parsed = urlparse(social_browser.social_search_url("youtube", query))
        self.assertEqual(parsed.netloc, "www.youtube.com")
        self.assertEqual(parsed.path, "/results")
        self.assertEqual(parse_qs(parsed.query)["search_query"], [query])

    def test_youtube_accepts_only_public_video_short_and_live_urls(self):
        expected = {
            "https://www.youtube.com/watch?v=abc123XYZ_-&list=PL123": (
                "https://www.youtube.com/watch?v=abc123XYZ_-"
            ),
            "https://youtu.be/abc123XYZ_-?si=tracking": (
                "https://www.youtube.com/watch?v=abc123XYZ_-"
            ),
            "https://www.youtube.com/shorts/abc123XYZ_-?feature=share": (
                "https://www.youtube.com/shorts/abc123XYZ_-"
            ),
            "https://www.youtube.com/live/abc123XYZ_-?feature=share": (
                "https://www.youtube.com/live/abc123XYZ_-"
            ),
        }
        for value, canonical in expected.items():
            with self.subTest(value=value):
                self.assertEqual(
                    social_browser._allowed_social_url("youtube", value),
                    canonical,
                )
        for value in (
            "https://www.youtube.com/results?search_query=aespa",
            "https://www.youtube.com/@aespa",
            "https://www.youtube.com/playlist?list=PL123",
            "https://example.com/watch?v=abc123XYZ_-",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    social_browser._allowed_social_url("youtube", value), ""
                )
        self.assertEqual(
            social_browser._youtube_video_identity(
                "https://www.youtube.com/shorts/abc123XYZ_-"
            ),
            social_browser._youtube_video_identity(
                "https://www.youtube.com/watch?v=abc123XYZ_-"
            ),
        )

    def test_search_match_compares_youtube_query(self):
        self.assertTrue(
            social_browser.matches_expected_social_search(
                "https://www.youtube.com/results?search_query=aespa+live",
                "https://www.youtube.com/results?search_query=aespa+live",
            )
        )
        self.assertFalse(
            social_browser.matches_expected_social_search(
                "https://www.youtube.com/results?search_query=unrelated",
                "https://www.youtube.com/results?search_query=aespa+live",
            )
        )

    def test_only_youtube_result_cards_survive_dom_extraction(self):
        class FakePage:
            def evaluate(self, _script):
                return [
                    {
                        "url": "https://www.youtube.com/watch?v=abc123XYZ_-&pp=x",
                        "visible_text": (
                            "aespa live stage Current Channel 3 days ago 12K views"
                        ),
                        "image_url": (
                            "https://i.ytimg.com/vi/abc123XYZ_-/hqdefault.jpg"
                        ),
                        "image_alt": "aespa live stage",
                        "source_kind": "result_card",
                        "dom_card_matched": True,
                    },
                    {
                        "url": "https://www.youtube.com/shorts/shortsABC12",
                        "visible_text": "aespa backstage Shorts Current Channel",
                        "image_url": (
                            "https://i.ytimg.com/vi/shortsABC12/hqdefault.jpg"
                        ),
                        "image_alt": "aespa backstage Shorts",
                        "source_kind": "result_card",
                        "dom_card_matched": True,
                    },
                    {
                        "url": "https://www.youtube.com/watch?v=nav123XYZ__",
                        "visible_text": "History navigation item",
                        "image_url": "",
                        "image_alt": "",
                        "source_kind": "generic_link",
                        "dom_card_matched": False,
                    },
                    {
                        "url": "https://www.youtube.com/@aespa",
                        "visible_text": "aespa channel",
                        "image_url": "https://yt3.ggpht.com/avatar",
                        "image_alt": "aespa",
                        "source_kind": "result_card",
                        "dom_card_matched": True,
                    },
                ]

        candidates = social_browser._extract_post_candidates(FakePage(), "youtube")
        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            {item["url"] for item in candidates},
            {
                "https://www.youtube.com/watch?v=abc123XYZ_-",
                "https://www.youtube.com/shorts/shortsABC12",
            },
        )
        self.assertTrue(
            all(item["source_kind"] == "result_card" for item in candidates)
        )

    def test_current_video_text_excludes_recommendations_and_comments(self):
        value = social_browser._bounded_youtube_video_text(
            _MetadataPage(), "Search Result Title"
        )
        self.assertIn("CURRENT VIDEO", value)
        self.assertIn("Current YouTube Video", value)
        self.assertIn("Current Channel", value)
        self.assertIn("2026-08-28", value)
        self.assertIn("Only this video's description", value)
        self.assertNotIn("Search Result Title", value)
        self.assertNotIn("recommendation", value.casefold())
        self.assertNotIn("comment", value.casefold())

    def test_native_cover_and_player_frame_are_the_only_assets(self):
        cover = _jpeg("cover")
        frame = _jpeg("frame")
        metadata = {
            "cover": "https://i.ytimg.com/vi/abc123XYZ_-/maxresdefault.jpg",
            "thumbnail_urls": [],
            "is_short": True,
        }
        with patch.object(
            social_browser, "_youtube_video_metadata", return_value=metadata
        ), patch.object(
            social_browser,
            "_youtube_cover_urls",
            return_value=[metadata["cover"]],
        ), patch.object(
            social_browser, "_download_post_image_jpeg", return_value=cover
        ), patch.object(
            social_browser, "_capture_youtube_video_frame", return_value=frame
        ):
            assets = social_browser._capture_social_post_assets(
                object(),
                "youtube",
                fallback_image_url=(
                    "https://i.ytimg.com/vi/abc123XYZ_-/hqdefault.jpg"
                ),
            )
        self.assertEqual(
            [asset["label"] for asset in assets],
            ["视频封面", "视频帧 1"],
        )
        self.assertNotIn("正文", [asset["label"] for asset in assets])

    def test_ad_player_is_never_captured_as_video_evidence(self):
        class FakeVideo:
            def bounding_box(self):
                return {"width": 640, "height": 360}

            def evaluate(self, script):
                if "ad-showing" in script:
                    return True
                raise AssertionError("ad video must not be decoded")

        class FakeLocators:
            def count(self):
                return 1

            def nth(self, _index):
                return FakeVideo()

        class FakePage:
            def locator(self, _selector):
                return FakeLocators()

        self.assertEqual(
            social_browser._capture_youtube_video_frame(FakePage()), b""
        )

    def test_opened_metadata_date_overrides_search_page_inference(self):
        items = [{
            "title": "Current YouTube Video",
            "time": "3 days ago",
            "resolved_date": "2026-08-29",
        }]
        details = [{
            "post_title": "Current YouTube Video",
            "visible_time_text": "2026-08-28",
            "evidence_level": "opened_multimodal",
        }]
        kept, kept_details, warnings, dropped = (
            tools.reconcile_social_detail_dates(
                items,
                details,
                selection_mode="RECENT",
                recency_days=7,
                current_date=date(2026, 9, 1),
            )
        )
        self.assertEqual(kept[0]["resolved_date"], "2026-08-28")
        self.assertEqual(kept[0]["date_source"], "opened_post")
        self.assertEqual(kept_details[0]["resolved_date"], "2026-08-28")
        self.assertEqual(dropped, 0)
        self.assertTrue(any("覆盖" in warning for warning in warnings))

    def test_route_and_prompts_treat_youtube_as_native_social_research(self):
        route = {
            "lane": "SEARCH",
            "confidence": 0.99,
            "reason": "The user explicitly requested YouTube videos.",
            "social_scope": "SOCIAL_RESEARCH",
            "social_platforms": ["youtube"],
            "search_scope": "SOCIAL_RESEARCH",
            "recommendation_domain": None,
            "local_knowledge_sufficiency": "NONE",
        }
        with patch.object(
            magi.tools, "run_ai_prompt", return_value=route
        ), patch.object(magi.tools, "unload_model"):
            result = magi.route_request("去 YouTube 搜索 aespa live clips")
        self.assertEqual(result["social_platforms"], ["youtube"])
        plan = melchior._authoritative_social_plan(result)
        self.assertEqual(plan["response_mode"], "SOCIAL_RESEARCH")
        self.assertEqual(plan["social_platforms"], ["youtube"])
        self.assertEqual(tools.SOCIAL_PLATFORM_NAMES["youtube"], "YouTube")

        gate = (ROOT / "prompts" / "magi_gate.txt").read_text(encoding="utf-8")
        query = (ROOT / "prompts" / "social_query.txt").read_text(
            encoding="utf-8"
        )
        vision = (ROOT / "prompts" / "social_post_introduction.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn('social_platforms ["youtube"]', gate)
        self.assertIn("@handles", query)
        self.assertIn("YouTube Shorts", vision)

    def test_runtime_has_youtube_detail_and_no_search_page_screenshots(self):
        source = (ROOT / "social_browser.py").read_text(encoding="utf-8")
        self.assertIn('elif target["platform"] == "youtube"', source)
        self.assertIn("_bounded_youtube_video_text", source)
        self.assertIn("_capture_youtube_video_frame", source)
        self.assertIn("SOCIAL YOUTUBE PLAYER ID MISMATCH", source)
        self.assertIn('platform in ("reddit", "youtube")', source)
        self.assertIn('target["platform"] != "youtube"', source)

    def test_runtime_mirrors_match(self):
        self.assertEqual(
            (ROOT / "social_browser.py").read_bytes(),
            (ROOT / "casper" / "social_browser.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "melchior.py").read_bytes(),
            (ROOT / "casper" / "melchior.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "tools.py").read_bytes(),
            (ROOT / "casper" / "tools.py").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
