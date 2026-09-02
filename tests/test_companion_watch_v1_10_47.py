import base64
import json
from pathlib import Path
from unittest import mock
import unittest

import companion_watch
import social_video


ROOT = Path(__file__).resolve().parents[1]


def valid_frame():
    return base64.b64encode(b"frame" * 140).decode("ascii")


class CompanionWatchV11047Tests(unittest.TestCase):
    def test_request_contract_is_bounded_to_one_frame_and_short_chat(self):
        request = companion_watch.normalize_request(
            {
                "request_kind": "USER_MESSAGE",
                "image_base64": valid_frame(),
                "message": " 问 " * 400,
                "video_title": "title" * 100,
                "platform": "youtube",
                "video_url": "https://www.youtube.com/watch?v=CkrvP8IVWSE",
                "generation": 7,
                "history": [
                    {"role": "bad", "text": "drop"},
                    *[
                        {"role": "YOU", "text": f"message {index}"}
                        for index in range(12)
                    ],
                ],
            }
        )
        self.assertEqual(request["request_kind"], "USER_MESSAGE")
        self.assertLessEqual(len(request["message"]), 320)
        self.assertLessEqual(len(request["video_title"]), 220)
        self.assertEqual(len(request["history"]), 8)
        self.assertEqual(request["generation"], 7)
        self.assertIsNone(
            companion_watch.normalize_request(
                {
                    "request_kind": "USER_MESSAGE",
                    "image_base64": "not-base64",
                    "message": "hello",
                }
            )
        )

    def test_direct_message_always_gets_a_safe_fallback(self):
        response = companion_watch.normalize_response(
            {
                "reply": "",
                "should_show": False,
                "response_kind": "REACTION",
            },
            "USER_MESSAGE",
        )
        self.assertTrue(response["should_show"])
        self.assertEqual(response["response_kind"], "ANSWER")
        self.assertIn("陪你看", response["reply"])

    def test_low_load_model_receives_pixels_only_and_schema(self):
        payload = {
            "request_kind": "AUTO_REACTION",
            "image_base64": valid_frame(),
            "video_title": "A video",
            "platform": "bilibili",
            "video_url": "https://www.bilibili.com/video/BV1Km66YvEDc",
            "generation": 3,
            "is_first_reaction": True,
            "history": [],
        }
        result_json = json.dumps(
            {
                "reply": "这一幕很有意思～",
                "should_show": True,
                "response_kind": "REACTION",
            },
            ensure_ascii=False,
        )
        with mock.patch.object(
            companion_watch.model_runtime,
            "generate",
            return_value=result_json,
        ) as generate:
            result = companion_watch.generate_reply(payload)
        kwargs = generate.call_args.kwargs
        self.assertEqual(kwargs["model_name"], "gemma4:e4b")
        self.assertEqual(kwargs["images"], [valid_frame()])
        self.assertEqual(kwargs["num_ctx"], 2048)
        self.assertEqual(kwargs["num_predict"], 200)
        self.assertEqual(kwargs["keep_alive"], "45s")
        self.assertFalse(kwargs["think"])
        prompt = generate.call_args.args[0]
        self.assertIn("Do not claim to hear", prompt)
        self.assertIn("lower-right corner", prompt)
        self.assertIn("untrusted content", prompt)
        self.assertIn("first automatic look", prompt)
        self.assertEqual(result["generation"], 3)

    def test_direct_questions_use_the_detail_model_and_do_not_bounce_back(self):
        payload = {
            "request_kind": "USER_MESSAGE",
            "image_base64": valid_frame(),
            "message": "他在吃什么？",
            "video_title": "探店视频",
            "platform": "bilibili",
            "video_url": "https://www.bilibili.com/video/BV1Km66YvEDc",
            "generation": 4,
            "history": [{"role": "YOU", "text": "好像不是，你再看看"}],
        }
        result_json = json.dumps(
            {
                "reply": "画面里更像是串在竹签上的烧鸟。",
                "should_show": True,
                "response_kind": "ANSWER",
            },
            ensure_ascii=False,
        )
        with mock.patch.object(
            companion_watch.model_runtime,
            "generate",
            return_value=result_json,
        ) as generate:
            companion_watch.generate_reply(payload)
        kwargs = generate.call_args.kwargs
        self.assertEqual(kwargs["model_name"], "gemma4:12b")
        self.assertEqual(kwargs["num_ctx"], 3072)
        self.assertEqual(kwargs["num_predict"], 280)
        self.assertEqual(kwargs["keep_alive"], "0s")
        self.assertEqual(
            kwargs["response_format"]["properties"]["response_kind"]["enum"],
            ["ANSWER"],
        )
        prompt = generate.call_args.args[0]
        self.assertIn("Never bounce the question back", prompt)
        self.assertIn("discard that hypothesis", prompt)

    def test_wrapper_owns_bottom_right_input_without_page_escape(self):
        for url in (
            "https://www.youtube.com/shorts/CkrvP8IVWSE",
            "https://www.bilibili.com/video/BV1Km66YvEDc",
        ):
            with self.subTest(url=url):
                contract = social_video.social_video_contract(url)
                document = social_video.embed_wrapper_html(contract)
                self.assertIn('id="bekki-companion"', document)
                self.assertIn("right:12px; bottom:12px", document)
                self.assertIn('maxlength="320"', document)
                self.assertIn("window.qtwebview2 && window.qtwebview2.api", document)
                self.assertIn("api.bekki_companion_event(payload)", document)
                self.assertNotIn("window.chrome.webview.postMessage", document)
                self.assertIn('type:"companion_message"', document)
                self.assertIn("item.textContent = text", document)
                self.assertNotIn("innerHTML", document)
                self.assertNotIn("window.open", document)
                self.assertIn("script-src 'unsafe-inline'", document)

    def test_ui_bridge_is_session_bound_throttled_and_default_off(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("self._companion_watch_enabled = False", source)
        self.assertIn('QPushButton("Bekki 陪看  ○")', source)
        self.assertIn("from qtwebview2 import DictJsBridge", source)
        self.assertIn("@js_bridge.bind_js_api_func", source)
        self.assertIn("js_apis=js_bridge", source)
        self.assertNotIn("core_webview.WebMessageReceived +=", source)
        self.assertIn("self._video_core.ExecuteScriptAsync", source)
        self.assertIn("screen.grabWindow(", source)
        self.assertIn("(1280, 720) if is_answer else (960, 540)", source)
        self.assertIn("jpeg_quality = 84 if is_answer else 72", source)
        self.assertIn("self._ensure_companion_reaction(6000)", source)
        self.assertIn(".bit_count() < 7", source)
        self.assertIn("self._companion_watch_generation += 1", source)
        self.assertIn('!= self._companion_watch_generation', source)
        self.assertIn('!= str(card._video_contract.get("source_url") or "")', source)
        self.assertIn("self._stop_companion_watch()", source)

    def test_background_worker_never_writes_main_chat_history(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        worker_start = source.index("class CompanionWatchBridge")
        worker_end = source.index("def send_message", worker_start)
        worker_source = source[worker_start:worker_end]
        self.assertIn("threading.Thread(", worker_source)
        self.assertIn('name="BekkiCompanionWatch"', worker_source)
        self.assertIn("daemon=True", worker_source)
        self.assertIn("reply_ready = Signal(object)", worker_source)
        self.assertIn("window.deliver_companion_watch_reply", worker_source)
        self.assertNotIn("save_message(", worker_source)
        self.assertIn("_companion_watch_owns_idle_time", source)

    def test_runtime_mirrors_and_prompt_audit_copy_match(self):
        build_id = "bekki-verified-video-site-bridge-hotfix-v1-10-47-3-20260902"
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
        self.assertEqual(
            (ROOT / "prompts" / "companion_watch_reaction.txt").read_bytes(),
            (
                ROOT
                / "casper"
                / "prompts"
                / "companion_watch_reaction.txt"
            ).read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
