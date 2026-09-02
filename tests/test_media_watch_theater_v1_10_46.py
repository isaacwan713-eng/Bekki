import ast
from pathlib import Path
import unittest
from unittest.mock import patch

import magi
import media_watch
import melchior
import tools
import video_sites
from casper import adapters
from casper import browser as casper_browser


ROOT = Path(__file__).resolve().parents[1]


def _watch_route():
    return {
        "lane": "SEARCH",
        "confidence": 0.99,
        "reason": "The requested outcome is to find media to watch.",
        "social_scope": "OTHER",
        "social_platforms": [],
        "search_scope": "MEDIA_WATCH",
        "recommendation_domain": None,
        "local_knowledge_sufficiency": "NONE",
    }


def _plan(topic="下饭视频", mode="RANDOM_ONE", sites=None):
    sites = list(sites or [])
    return {
        "topic": topic,
        "selection_mode": mode,
        "content_kind": "CATEGORY" if mode == "RANDOM_ONE" else "VIDEO",
        "episode_hint": None,
        "requested_sites": sites,
        "site_scope_explicit": bool(sites),
    }


class MediaWatchIntentV11046Tests(unittest.TestCase):
    def test_random_bilibili_request_is_clean_and_hard_bounded(self):
        message = "去B站找一个下饭视频"
        sites = media_watch.extract_requested_sites(message)
        self.assertEqual(sites, ["bilibili.com"])
        self.assertEqual(media_watch.selection_mode(message), "RANDOM_ONE")
        self.assertEqual(media_watch.fallback_topic(message, sites), "下饭视频")

    def test_named_work_defaults_to_exact_cross_site(self):
        message = "我现在想看名侦探柯南"
        self.assertEqual(media_watch.extract_requested_sites(message), [])
        self.assertEqual(media_watch.selection_mode(message), "EXACT")
        self.assertEqual(media_watch.fallback_topic(message, []), "名侦探柯南")

    def test_literal_public_domain_is_preserved_without_path_noise(self):
        message = "请从example.com/videos找一个猫咪视频"
        sites = media_watch.extract_requested_sites(message)
        self.assertEqual(sites, ["example.com"])
        self.assertEqual(media_watch.fallback_topic(message, sites), "猫咪视频")

    def test_followup_contract_distinguishes_enter_next_and_new_request(self):
        self.assertEqual(media_watch.classify_followup("可以"), "ENTER_THEATER")
        self.assertEqual(media_watch.classify_followup("换一个"), "NEXT")
        self.assertEqual(media_watch.classify_followup("不用了"), "CANCEL")
        self.assertEqual(
            media_watch.classify_followup("我想看另一个具体节目"),
            "NEW_REQUEST",
        )


class MediaWatchRoutingV11046Tests(unittest.TestCase):
    def test_magi_accepts_media_watch_as_non_social_search(self):
        route = magi._valid_ai_route(_watch_route())
        self.assertIsNotNone(route)
        self.assertEqual(route["search_scope"], "MEDIA_WATCH")
        self.assertEqual(route["social_scope"], "OTHER")
        self.assertEqual(route["social_platforms"], [])

    def test_melchior_authoritative_watch_plan_has_closed_invariants(self):
        plan = melchior._authoritative_media_watch_plan(_watch_route())
        self.assertEqual(plan["response_mode"], "MEDIA_WATCH")
        self.assertTrue(plan["needs_search"])
        self.assertEqual(plan["research_depth"], "watch_discovery")
        self.assertEqual(plan["source_policy"], "user_bounded_watch_sources")
        self.assertEqual(plan["research_profile"], "media_watch")
        self.assertEqual(plan["social_platforms"], [])

    def test_plan_request_bypasses_general_router_for_authoritative_watch(self):
        with patch.object(
            melchior.tools,
            "run_ai_prompt",
            side_effect=AssertionError("authoritative MEDIA_WATCH must bypass"),
        ) as model:
            plan = melchior.plan_request(
                "去B站找一个下饭视频",
                magi_route=_watch_route(),
            )
        model.assert_not_called()
        self.assertEqual(plan["response_mode"], "MEDIA_WATCH")

    def test_prompts_explicitly_separate_watch_from_social_research(self):
        for relative in (
            "prompts/magi_gate.txt",
            "prompts/magi_audit.txt",
            "prompts/melchior_router.txt",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("MEDIA_WATCH", source)
            self.assertIn("去 B 站找一个下饭视频", source)
            self.assertIn("hard", source.casefold())

    def test_adapter_dispatches_to_watch_controller(self):
        expected = {"status": "OK", "cards": [], "direct_reply": "found"}
        plan = {"response_mode": "MEDIA_WATCH", "risk": "low"}
        with patch.object(tools, "unload_model", return_value=True), patch.object(
            casper_browser,
            "media_watch_controller",
            return_value=expected,
        ) as controller:
            result, _context = adapters.execute_mode(
                "去B站找一个下饭视频",
                plan,
                {},
                "",
                lambda _value: None,
            )
        self.assertEqual(result, expected)
        controller.assert_called_once()


class MediaWatchExecutionV11046Tests(unittest.TestCase):
    bilibili_one = {
        "title": "下饭视频：一小时美食纪录片",
        "description": "轻松的下饭视频",
        "url": "https://www.bilibili.com/video/BV1Km66YvEDc",
        "domain": "www.bilibili.com",
        "image_url": "https://i0.hdslb.com/example-1.jpg",
    }
    bilibili_two = {
        "title": "下饭视频：城市夜宵纪录",
        "description": "另一个下饭视频",
        "url": "https://www.bilibili.com/video/BV1XX411c7mD",
        "domain": "bilibili.com",
        "image_url": "https://i0.hdslb.com/example-2.jpg",
    }
    youtube = {
        "title": "下饭视频 from YouTube",
        "description": "下饭视频",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "domain": "youtube.com",
    }

    def test_explicit_bilibili_never_accepts_youtube_padding(self):
        with patch.object(
            casper_browser,
            "_discover_native_media_watch",
            return_value=([], []),
        ), patch.object(
            casper_browser,
            "discover_web",
            return_value={
                "status": "OK",
                "results": [self.youtube, self.bilibili_one],
            },
        ):
            result = casper_browser.media_watch_controller(
                "去B站找一个下饭视频",
                preplanned=_plan(sites=["bilibili.com"]),
                chooser=lambda pool: pool[0],
            )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["cards"][0]["url"], self.bilibili_one["url"])
        self.assertTrue(
            all("site:bilibili.com/video" in query for query in result["queries"])
        )
        self.assertNotIn("youtube.com", result["query"])

    def test_random_chooser_and_next_exclusion_select_a_new_url(self):
        with patch.object(
            casper_browser,
            "_discover_native_media_watch",
            return_value=([], []),
        ), patch.object(
            casper_browser,
            "discover_web",
            return_value={
                "status": "OK",
                "results": [self.bilibili_one, self.bilibili_two],
            },
        ):
            result = casper_browser.media_watch_controller(
                "去B站找一个下饭视频",
                preplanned=_plan(sites=["bilibili.com"]),
                excluded_urls=[self.bilibili_one["url"]],
                chooser=lambda pool: pool[0],
            )
        self.assertEqual(result["cards"][0]["url"], self.bilibili_two["url"])
        pending = result["pending_action"]["approval_payload"]
        self.assertIn(self.bilibili_one["url"], pending["excluded_urls"])
        self.assertIn(self.bilibili_two["url"], pending["excluded_urls"])

    def test_playable_result_asks_for_theater_and_persists_one_choice(self):
        with patch.object(
            casper_browser,
            "_discover_native_media_watch",
            return_value=([], []),
        ), patch.object(
            casper_browser,
            "discover_web",
            return_value={"status": "OK", "results": [self.bilibili_one]},
        ):
            result = casper_browser.media_watch_controller(
                "去B站找一个下饭视频",
                preplanned=_plan(sites=["bilibili.com"]),
                chooser=lambda pool: pool[0],
            )
        self.assertIn("进入影院模式", result["direct_reply"])
        self.assertEqual(result["pending_action"]["type"], "media_watch_choice")
        self.assertEqual(
            result["pending_action"]["approval_payload"]["selected_url"],
            self.bilibili_one["url"],
        )

    def test_non_inline_site_is_link_only_and_never_claims_theater(self):
        candidate = {
            "title": "纪录片观看页面",
            "description": "纪录片",
            "url": "https://example.com/watch/123",
            "domain": "example.com",
        }
        with patch.object(
            casper_browser,
            "_discover_native_media_watch",
            return_value=([], []),
        ), patch.object(
            video_sites,
            "is_verified",
            return_value=True,
        ), patch.object(
            casper_browser,
            "discover_web",
            return_value={"status": "OK", "results": [candidate]},
        ):
            result = casper_browser.media_watch_controller(
                "从 example.com 看纪录片",
                preplanned=_plan("纪录片", "EXACT", ["example.com"]),
            )
        self.assertEqual(result["status"], "OK")
        self.assertIsNone(result["pending_action"])
        self.assertIn("不能在 Bekki 内嵌播放", result["direct_reply"])

    def test_exact_work_rejects_commentary_clip_substitution(self):
        derivative = {
            "title": "名侦探柯南解说 clip",
            "description": "名侦探柯南剧情盘点",
            "url": self.bilibili_one["url"],
            "domain": "bilibili.com",
        }
        with patch.object(
            casper_browser,
            "_discover_native_media_watch",
            return_value=([], []),
        ), patch.object(
            casper_browser,
            "discover_web",
            return_value={"status": "OK", "results": [derivative]},
        ):
            result = casper_browser.media_watch_controller(
                "我想看名侦探柯南",
                preplanned=_plan("名侦探柯南", "EXACT", ["bilibili.com"]),
            )
        self.assertEqual(result["status"], "NO_WATCH_RESULT")
        self.assertEqual(result["cards"], [])

    def test_native_bilibili_result_wins_without_general_web_search(self):
        native_card = {
            "platform": "bilibili",
            "url": self.bilibili_one["url"],
            "title": "真正适合下饭的纪录片",
            "description": "轻松下饭，随机看看",
            "author": "测试UP主",
            "published": "2026-09-01",
            "visible_text": "真正适合下饭的纪录片 UP主：测试UP主",
            "image_url": self.bilibili_one["image_url"],
            "image_alt": "真正适合下饭的纪录片",
            "source_kind": "network_result",
        }
        with patch("social_browser.open_social_search", return_value={
            "url": "https://search.bilibili.com/all?keyword=%E4%B8%8B%E9%A5%AD%E8%A7%86%E9%A2%91",
        }) as opened, patch(
            "social_browser.inspect_active_social_page",
            return_value={"post_candidates": [native_card]},
        ) as inspected, patch(
            "social_browser.close_social_browser",
            return_value=None,
        ) as closed, patch.object(
            casper_browser,
            "discover_web",
            side_effect=AssertionError("native result must skip Google/Bing"),
        ) as web:
            result = casper_browser.media_watch_controller(
                "去B站找一个下饭视频",
                preplanned=_plan(sites=["bilibili.com"]),
                chooser=lambda pool: pool[0],
            )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["cards"][0]["url"], self.bilibili_one["url"])
        self.assertEqual(result["queries"], ["bilibili_native:下饭视频"])
        opened.assert_called_once_with(
            "bilibili", "下饭视频", selection_mode="RELEVANCE"
        )
        inspected.assert_called_once()
        closed.assert_called_once()
        web.assert_not_called()

    def test_empty_native_search_uses_bounded_web_fallback(self):
        with patch.object(
            casper_browser,
            "_discover_native_media_watch",
            return_value=([], ["bilibili_native:下饭视频"]),
        ), patch.object(
            casper_browser,
            "discover_web",
            return_value={"status": "OK", "results": [self.bilibili_one]},
        ) as web:
            result = casper_browser.media_watch_controller(
                "去B站找一个下饭视频",
                preplanned=_plan(sites=["bilibili.com"]),
                chooser=lambda pool: pool[0],
            )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["cards"][0]["url"], self.bilibili_one["url"])
        self.assertIn("bilibili_native:下饭视频", result["queries"])
        self.assertTrue(
            any(query.startswith("site:bilibili.com/video ") for query in result["queries"])
        )
        web.assert_called_once()

    def test_irrelevant_native_result_does_not_block_web_fallback(self):
        unrelated = dict(self.bilibili_one)
        unrelated.update({
            "title": "猫咪睡觉直播",
            "description": "与请求无关",
            "url": "https://www.bilibili.com/video/BV1AA411c7mD",
        })
        with patch.object(
            casper_browser,
            "_discover_native_media_watch",
            return_value=([unrelated], ["bilibili_native:下饭视频"]),
        ), patch.object(
            casper_browser,
            "discover_web",
            return_value={"status": "OK", "results": [self.bilibili_two]},
        ) as web:
            result = casper_browser.media_watch_controller(
                "去B站找一个下饭视频",
                preplanned=_plan(sites=["bilibili.com"]),
                chooser=lambda pool: pool[0],
            )
        self.assertEqual(result["cards"][0]["url"], self.bilibili_two["url"])
        web.assert_called_once()

    def test_native_discovery_opens_only_the_explicit_site(self):
        with patch(
            "social_browser.open_social_search",
            return_value={"url": "https://search.bilibili.com/all?keyword=test"},
        ) as opened, patch(
            "social_browser.inspect_active_social_page",
            return_value={"post_candidates": []},
        ), patch("social_browser.close_social_browser", return_value=None):
            candidates, queries = casper_browser._discover_native_media_watch(
                _plan(sites=["bilibili.com"])
            )
        self.assertEqual(candidates, [])
        self.assertEqual(queries, ["bilibili_native:下饭视频"])
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(opened.call_args.args[0], "bilibili")

    def test_native_converter_keeps_structured_bilibili_metadata(self):
        converted = casper_browser._native_media_watch_candidate(
            {
                "url": self.bilibili_one["url"],
                "title": "下饭纪录片",
                "description": "一小时完整版",
                "author": "UP主甲",
                "published": "2026-09-01",
                "visible_text": "fallback text",
                "image_url": self.bilibili_one["image_url"],
            },
            "bilibili",
        )
        self.assertEqual(converted["title"], "下饭纪录片")
        self.assertEqual(converted["author"], "UP主甲")
        self.assertEqual(converted["published"], "2026-09-01")
        self.assertEqual(converted["discovery_engine"], "bilibili_native")


class TheaterUiContractV11046Tests(unittest.TestCase):
    def test_theater_is_an_in_window_layer_reusing_the_same_video_host(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        window_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "BekkiWindow"
        )
        enter_method = next(
            node
            for node in window_class.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "enter_theater_mode"
        )
        enter_source = ast.unparse(enter_method)
        self.assertIn('self.theater_overlay = QFrame(self)', source)
        self.assertIn("card._attach_video_host_to_theater", enter_source)
        self.assertNotIn("QDialog", enter_source)
        self.assertNotIn("QDesktopServices", enter_source)

    def test_escape_exits_theater_before_bekki_fullscreen(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        start = source.index("def _exit_fullscreen_if_active")
        end = source.index("def _sync_fullscreen_ui", start)
        method = source[start:end]
        self.assertLess(
            method.index("self.exit_theater_mode()"),
            method.index("self.toggle_fullscreen()"),
        )

    def test_backend_confirmation_is_applied_after_cards_are_rendered(self):
        main_source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('"type": "enter_theater_mode"', main_source)
        self.assertIn("window.perform_ui_action(action)", main_source)
        self.assertIn("QTimer.singleShot(", main_source)
        self.assertIn("self.chat.find_card_by_url(url)", (ROOT / "ui.py").read_text(encoding="utf-8"))

    def test_stop_and_chat_clear_release_theater_before_qt_children(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("if self._theater_active:", source)
        self.assertIn("handler(self)", source)
        self.assertIn("card._stop_inline_video(refresh=False)", source)
        self.assertIn("def closeEvent(self, event):", source)

    def test_runtime_mirrors_include_theater_and_watch_plan(self):
        for left, right in (
            ("ui.py", "casper/ui.py"),
            ("tools.py", "casper/tools.py"),
            ("melchior.py", "casper/melchior.py"),
            (
                "prompts/media_watch_plan.txt",
                "casper/prompts/media_watch_plan.txt",
            ),
            (
                "prompts/melchior_router.txt",
                "casper/prompts/melchior_router.txt",
            ),
        ):
            self.assertEqual((ROOT / left).read_bytes(), (ROOT / right).read_bytes())


if __name__ == "__main__":
    unittest.main()
