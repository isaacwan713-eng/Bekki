import json
import sys
import types
import unittest
from unittest.mock import Mock, patch

from casper import hoyoplay


class HoYoPlayAutomationTests(unittest.TestCase):
    def test_non_windows_fails_closed(self):
        with patch.object(hoyoplay.os, "name", "posix"):
            result = hoyoplay.launch_genshin_via_ui()
        self.assertEqual(result["status"], "unsupported_platform")

    def test_windows_automation_returns_last_json_result(self):
        completed = types.SimpleNamespace(
            returncode=0,
            stdout=(
                "UIA diagnostic\n"
                + json.dumps(
                    {
                        "status": "game_opened",
                        "window": "HoYoPlay",
                        "control": "Start Game",
                    }
                )
                + "\n"
            ),
            stderr="",
        )
        with patch.object(hoyoplay.os, "name", "nt"), patch.object(
            hoyoplay.subprocess,
            "run",
            return_value=completed,
        ) as runner:
            result = hoyoplay.launch_genshin_via_ui(timeout_seconds=10)
        self.assertEqual(result["status"], "game_opened")
        command = runner.call_args.args[0]
        self.assertIn("powershell.exe", command)
        self.assertIn("UIAutomationClient", command[-1])
        self.assertIn("GenshinImpact", command[-1])
        self.assertIn("Start Game", command[-1])

    def test_uia_invisible_identity_falls_back_to_window_vision(self):
        completed = types.SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"status": "game_identity_not_visible"}),
            stderr="",
        )
        visual_result = {
            "status": "launch_dispatched",
            "window": "HoYoPlay",
            "control": "Start Game",
            "route": "vision_verified_click",
        }
        with patch.object(hoyoplay.os, "name", "nt"), patch.object(
            hoyoplay.subprocess,
            "run",
            return_value=completed,
        ), patch.object(
            hoyoplay,
            "_launch_genshin_via_vision",
            return_value=visual_result,
        ) as fallback:
            result = hoyoplay.launch_genshin_via_ui(timeout_seconds=10)
        fallback.assert_called_once_with()
        self.assertEqual(result["route"], "vision_verified_click")

    def test_visual_plan_sends_png_to_small_vision_model_with_schema(self):
        captured = []
        response = {
            "game_identity": "GENSHIN",
            "button_visible": True,
            "button_text": "Start Game",
            "center_x_1000": 800,
            "center_y_1000": 850,
            "confidence": "high",
            "reason": "Genshin page and Start Game button are visible",
        }
        audit_response = {
            "target_correct": True,
            "corrected_x_1000": 800,
            "corrected_y_1000": 850,
            "confidence": "high",
            "reason": "The red crosshair is inside the Start Game button",
        }

        def call_model(_prompt, **kwargs):
            captured.append(kwargs)
            return json.dumps(response if len(captured) == 1 else audit_response)

        fake_tools = types.SimpleNamespace(
            unload_model=lambda _name: None,
            wait_for_model_unloaded=lambda _name, timeout_seconds: True,
            call_model=call_model,
        )
        with patch.dict(sys.modules, {"tools": fake_tools}), patch.object(
            hoyoplay,
            "_annotate_visual_target",
            return_value=b"annotated-png",
        ):
            result = hoyoplay._visual_launch_plan(b"valid-png-bytes")
        self.assertEqual(result["game_identity"], "GENSHIN")
        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0]["model_name"], "gemma4:e4b")
        self.assertEqual(captured[0]["num_ctx"], 2048)
        self.assertTrue(captured[0]["response_format"])
        self.assertEqual(len(captured[0]["images"]), 1)
        self.assertEqual(captured[1]["response_format"], hoyoplay._TARGET_AUDIT_SCHEMA)

    def test_visual_target_correction_must_pass_a_second_marker_audit(self):
        responses = [
            {
                "game_identity": "GENSHIN",
                "button_visible": True,
                "button_text": "开始游戏",
                "center_x_1000": 520,
                "center_y_1000": 640,
                "confidence": "high",
                "reason": "Initial target",
            },
            {
                "target_correct": True,
                "corrected_x_1000": 623,
                "corrected_y_1000": 848,
                "confidence": "high",
                "reason": "Contradictory live-style response with a new point",
            },
            {
                "target_correct": True,
                "corrected_x_1000": 623,
                "corrected_y_1000": 848,
                "confidence": "high",
                "reason": "Corrected marker is inside the launch button",
            },
        ]
        fake_tools = types.SimpleNamespace(
            unload_model=lambda _name: None,
            wait_for_model_unloaded=lambda _name, timeout_seconds: True,
            call_model=lambda *_args, **_kwargs: json.dumps(responses.pop(0)),
        )
        with patch.dict(sys.modules, {"tools": fake_tools}), patch.object(
            hoyoplay,
            "_annotate_visual_target",
            return_value=b"annotated-png",
        ):
            result = hoyoplay._visual_launch_plan(b"valid-png-bytes")
        self.assertEqual(result["center_x_1000"], 623)
        self.assertEqual(result["center_y_1000"], 848)
        self.assertEqual(result["confidence"], "high")

    def test_visual_model_failure_is_not_reported_as_target_unverified(self):
        fake_tools = types.SimpleNamespace(
            unload_model=lambda _name: None,
            wait_for_model_unloaded=lambda _name, timeout_seconds: True,
            call_model=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("CUDA initialization failed")
            ),
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            plan = hoyoplay._visual_launch_plan(b"valid-png-bytes")
        self.assertEqual(plan["_runtime_status"], "vision_model_unavailable")

    def test_visual_click_requires_identity_button_and_high_confidence(self):
        rect = {
            "left": 100,
            "top": 50,
            "right": 1100,
            "bottom": 650,
            "width": 1000,
            "height": 600,
        }
        valid = {
            "game_identity": "GENSHIN",
            "button_visible": True,
            "button_text": "Start Game",
            "center_x_1000": 800,
            "center_y_1000": 850,
            "confidence": "high",
        }
        self.assertEqual(
            hoyoplay._validated_click_point(valid, rect),
            (900, 560),
        )
        invalid = dict(valid, game_identity="NOT_VISIBLE")
        self.assertIsNone(hoyoplay._validated_click_point(invalid, rect))

    def test_imagegrab_failure_uses_native_window_capture(self):
        rect = {
            "hwnd": 42,
            "left": 0,
            "top": 0,
            "right": 1000,
            "bottom": 700,
            "width": 1000,
            "height": 700,
        }
        fake_image_grab = types.SimpleNamespace(
            grab=lambda **_kwargs: (_ for _ in ()).throw(
                OSError("screen grab failed")
            )
        )
        fake_pil = types.ModuleType("PIL")
        fake_pil.ImageGrab = fake_image_grab
        with patch.dict(sys.modules, {"PIL": fake_pil}), patch.object(
            hoyoplay,
            "_capture_window_png_native",
            return_value=b"native-png",
        ) as native_capture:
            result = hoyoplay._capture_window_png(rect)
        native_capture.assert_called_once_with(rect)
        self.assertEqual(result, b"native-png")

    def test_native_capture_is_disabled_outside_windows(self):
        with patch.object(hoyoplay.os, "name", "posix"):
            self.assertEqual(
                hoyoplay._capture_window_png_native(
                    {"hwnd": 42, "width": 1000, "height": 700}
                ),
                b"",
            )

    def test_click_uses_64_bit_safe_hwnd_and_exact_foreground(self):
        user32 = types.SimpleNamespace(
            ShowWindowAsync=Mock(return_value=True),
            BringWindowToTop=Mock(return_value=True),
            SetForegroundWindow=Mock(return_value=True),
            GetForegroundWindow=Mock(return_value=42),
            SetCursorPos=Mock(return_value=True),
            mouse_event=Mock(return_value=None),
        )
        fake_windll = types.SimpleNamespace(user32=user32)
        with patch.object(hoyoplay.os, "name", "nt"), patch.object(
            hoyoplay.ctypes,
            "windll",
            fake_windll,
            create=True,
        ), patch.object(hoyoplay.time, "sleep", return_value=None):
            clicked = hoyoplay._click_foreground_window(42, (900, 560))
        self.assertTrue(clicked)
        user32.SetCursorPos.assert_called_once_with(900, 560)
        self.assertEqual(user32.mouse_event.call_count, 2)

    def test_click_never_dispatches_to_a_different_foreground_window(self):
        user32 = types.SimpleNamespace(
            ShowWindowAsync=Mock(return_value=True),
            BringWindowToTop=Mock(return_value=True),
            SetForegroundWindow=Mock(return_value=False),
            GetForegroundWindow=Mock(return_value=99),
            SetCursorPos=Mock(return_value=True),
            mouse_event=Mock(return_value=None),
        )
        fake_windll = types.SimpleNamespace(user32=user32)
        with patch.object(hoyoplay.os, "name", "nt"), patch.object(
            hoyoplay.ctypes,
            "windll",
            fake_windll,
            create=True,
        ), patch.object(hoyoplay.time, "sleep", return_value=None):
            clicked = hoyoplay._click_foreground_window(42, (900, 560))
        self.assertFalse(clicked)
        user32.SetCursorPos.assert_not_called()
        user32.mouse_event.assert_not_called()

    def test_click_falls_back_to_send_input_when_set_cursor_is_rejected(self):
        virtual_metrics = {76: -1920, 77: 0, 78: 3840, 79: 1080}
        user32 = types.SimpleNamespace(
            ShowWindowAsync=Mock(return_value=True),
            BringWindowToTop=Mock(return_value=True),
            SetForegroundWindow=Mock(return_value=True),
            GetForegroundWindow=Mock(return_value=42),
            SetCursorPos=Mock(return_value=False),
            mouse_event=Mock(return_value=None),
            GetSystemMetrics=Mock(side_effect=lambda index: virtual_metrics[index]),
            SendInput=Mock(return_value=1),
        )
        fake_windll = types.SimpleNamespace(user32=user32)
        with patch.object(hoyoplay.os, "name", "nt"), patch.object(
            hoyoplay.ctypes,
            "windll",
            fake_windll,
            create=True,
        ), patch.object(hoyoplay.time, "sleep", return_value=None):
            clicked = hoyoplay._click_foreground_window(42, (900, 560))
        self.assertTrue(clicked)
        self.assertEqual(user32.SendInput.call_count, 3)
        user32.mouse_event.assert_not_called()


if __name__ == "__main__":
    unittest.main()
