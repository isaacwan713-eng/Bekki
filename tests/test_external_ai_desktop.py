import unittest
from unittest.mock import Mock, patch

from casper import external_ai
from casper import external_ai_desktop


class ExternalAIDesktopTests(unittest.TestCase):
    def test_chinese_question_drops_model_added_english_translation(self):
        cleaned = external_ai._preserve_requested_language(
            "帮我问 ChatGPT：为什么猫会呼噜？",
            "为什么猫会呼噜？ (Why do cats purr?)",
        )
        self.assertEqual(cleaned, "为什么猫会呼噜？")

    def test_explicit_translation_request_keeps_requested_bilingual_text(self):
        cleaned = external_ai._preserve_requested_language(
            "请把问题翻译成英文后问 ChatGPT：为什么猫会呼噜？",
            "Why do cats purr?",
        )
        self.assertEqual(cleaned, "Why do cats purr?")

    def test_public_transport_is_desktop_only(self):
        with (
            patch.object(
                external_ai_desktop,
                "ask_prompt",
                return_value={"status": "DESKTOP_APP_NOT_INSTALLED"},
            ) as desktop,
        ):
            result = external_ai.ask_prompt("为什么猫会呼噜？")
        self.assertEqual(result["status"], "DESKTOP_APP_NOT_INSTALLED")
        desktop.assert_called_once_with("为什么猫会呼噜？", source_kind="user_explicit")

    def test_missing_desktop_app_fails_without_sending(self):
        Desktop = Mock()
        keyboard = Mock()
        with (
            patch.object(external_ai_desktop.sys, "platform", "win32"),
            patch.object(external_ai_desktop, "_load_uia", return_value=(Desktop, keyboard)),
            patch.object(external_ai_desktop, "_find_chatgpt_window", return_value=None),
            patch.object(external_ai_desktop, "_chatgpt_app_id", return_value=""),
            patch.object(external_ai_desktop, "_launch_app") as launch,
        ):
            result = external_ai_desktop.ask_prompt("hello")
        self.assertEqual(result["status"], "DESKTOP_APP_NOT_INSTALLED")
        self.assertFalse(result["prompt_sent"])
        launch.assert_not_called()

    def test_desktop_success_returns_unverified_answer(self):
        Desktop = Mock()
        keyboard = Mock()
        window = Mock()
        editor = Mock()
        with (
            patch.object(external_ai_desktop.sys, "platform", "win32"),
            patch.object(external_ai_desktop, "_load_uia", return_value=(Desktop, keyboard)),
            patch.object(external_ai_desktop, "_find_chatgpt_window", return_value=window),
            patch.object(external_ai_desktop, "_focus_window", return_value=True),
            patch.object(
                external_ai_desktop,
                "_wait_for_prompt",
                return_value=(window, editor, "READY"),
            ),
            patch.object(external_ai_desktop, "_accessible_texts", return_value=[]),
            patch.object(external_ai_desktop, "_buttons_named", return_value=[]),
            patch.object(external_ai_desktop, "_enter_prompt", return_value="SENT") as entered,
            patch.object(external_ai_desktop, "_foreground_window_handle", return_value=101),
            patch.object(external_ai_desktop, "_background_after_send", return_value=False) as backgrounded,
            patch.object(external_ai_desktop, "_minimize_after_read") as minimized,
            patch.object(
                external_ai_desktop,
                "_wait_for_answer",
                return_value="Cats may purr to communicate.",
            ) as waited,
        ):
            result = external_ai_desktop.ask_prompt("为什么猫会呼噜？")
        entered.assert_called_once_with(editor, keyboard, "为什么猫会呼噜？")
        backgrounded.assert_called_once_with(window, 101)
        self.assertTrue(waited.call_args.kwargs["include_hidden"])
        minimized.assert_called_once_with(window, False)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["provider"], "ChatGPT Desktop")
        self.assertEqual(result["verification_status"], "UNVERIFIED_EXTERNAL_AI")
        self.assertTrue(result["prompt_sent"])

    def test_timeout_never_retries_or_claims_an_answer(self):
        Desktop = Mock()
        keyboard = Mock()
        window = Mock()
        with (
            patch.object(external_ai_desktop.sys, "platform", "win32"),
            patch.object(external_ai_desktop, "_load_uia", return_value=(Desktop, keyboard)),
            patch.object(external_ai_desktop, "_find_chatgpt_window", return_value=window),
            patch.object(external_ai_desktop, "_focus_window", return_value=True),
            patch.object(
                external_ai_desktop,
                "_wait_for_prompt",
                return_value=(window, Mock(), "READY"),
            ),
            patch.object(external_ai_desktop, "_accessible_texts", return_value=[]),
            patch.object(external_ai_desktop, "_buttons_named", return_value=[]),
            patch.object(external_ai_desktop, "_enter_prompt", return_value="SENT"),
            patch.object(external_ai_desktop, "_foreground_window_handle", return_value=101),
            patch.object(external_ai_desktop, "_background_after_send", return_value=False),
            patch.object(external_ai_desktop, "_minimize_after_read"),
            patch.object(external_ai_desktop, "_wait_for_answer", return_value=""),
        ):
            result = external_ai_desktop.ask_prompt("hello")
        self.assertEqual(result["status"], "DESKTOP_RESPONSE_TIMEOUT")
        self.assertTrue(result["prompt_sent"])
        self.assertNotIn("answer", result)

    def test_logged_out_desktop_requests_visible_login_without_send(self):
        Desktop = Mock()
        keyboard = Mock()
        window = Mock()
        with (
            patch.object(external_ai_desktop.sys, "platform", "win32"),
            patch.object(external_ai_desktop, "_load_uia", return_value=(Desktop, keyboard)),
            patch.object(external_ai_desktop, "_find_chatgpt_window", return_value=window),
            patch.object(external_ai_desktop, "_focus_window", return_value=True),
            patch.object(
                external_ai_desktop,
                "_wait_for_prompt",
                return_value=(window, None, "LOGIN_REQUIRED"),
            ),
            patch.object(external_ai_desktop, "_enter_prompt") as entered,
        ):
            result = external_ai_desktop.ask_prompt("hello")
        self.assertEqual(result["status"], "DESKTOP_LOGIN_REQUIRED")
        self.assertFalse(result["prompt_sent"])
        entered.assert_not_called()

    def test_prompt_entry_uses_unicode_sendinput_when_clipboard_is_busy(self):
        keyboard = Mock()
        editor = Mock()
        editor.set_edit_text.side_effect = RuntimeError("no value pattern")
        with (
            patch.object(external_ai_desktop, "_read_clipboard_text", return_value="old"),
            patch.object(external_ai_desktop, "_write_clipboard_text", return_value=False),
            patch.object(external_ai_desktop, "_type_unicode_text", return_value=True) as typed,
        ):
            status = external_ai_desktop._enter_prompt(editor, keyboard, "为什么猫会呼噜？")
        typed.assert_called_once_with("为什么猫会呼噜？")
        keyboard.send_keys.assert_called_once_with("{ENTER}", pause=0.03)
        self.assertEqual(status, "SENT")

    def test_user_message_label_is_never_an_answer(self):
        answer = external_ai_desktop._new_text_answer(
            [],
            ["You said:", "为什么猫会呼噜？"],
            "为什么猫会呼噜？",
        )
        self.assertEqual(answer, "")

    def test_substantive_assistant_text_is_accepted(self):
        answer = external_ai_desktop._new_text_answer(
            [],
            ["You said:", "ChatGPT said: 猫呼噜与喉部肌肉的节律活动有关。"],
            "为什么猫会呼噜？",
        )
        self.assertEqual(answer, "猫呼噜与喉部肌肉的节律活动有关。")

    def test_old_offscreen_answer_is_rejected_without_this_turn_prompt_anchor(self):
        answer = external_ai_desktop._anchored_text_answer(
            ["ChatGPT said: 棒球横向位移可能超过本垒板宽度。"],
            "SNH48的成员是如何分配到各个分队的？",
        )
        self.assertEqual(answer, "")

    def test_answer_after_exact_prompt_anchor_is_accepted(self):
        answer = external_ai_desktop._anchored_text_answer(
            [
                "ChatGPT said: 棒球横向位移可能超过本垒板宽度。",
                "You said: SNH48的成员是如何分配到各个分队的？",
                "ChatGPT said: SNH48会依据运营安排、成员特点与队伍需求调整分队。",
            ],
            "SNH48的成员是如何分配到各个分队的？",
        )
        self.assertEqual(
            answer,
            "SNH48会依据运营安排、成员特点与队伍需求调整分队。",
        )

    def test_prompt_anchor_ignores_only_uia_wrapping_artifacts(self):
        prompt = "SNH48现在有哪些正式分队？成员现在如何分配？"
        index = external_ai_desktop._prompt_anchor_index(
            ["You said: SNH48现在有哪些正式分队？\u200b\n成员现在如何分配？"],
            prompt,
        )
        self.assertEqual(index, 0)

    def test_repeated_old_prompt_is_not_a_new_text_answer(self):
        prompt = "SNH48现在有哪些正式分队？"
        before = [
            "You said: " + prompt,
            "ChatGPT said: 旧回答。",
        ]
        self.assertEqual(
            external_ai_desktop._anchored_text_answer_since(
                before, list(before), prompt
            ),
            "",
        )
        current = [
            *before,
            "You said: " + prompt,
            "ChatGPT said: 新回答。",
        ]
        self.assertEqual(
            external_ai_desktop._anchored_text_answer_since(
                before, current, prompt
            ),
            "新回答。",
        )

    def test_new_copy_control_is_detected_when_virtualization_keeps_same_count(self):
        old = Mock()
        old.element_info.runtime_id = (1, 10)
        new = Mock()
        new.element_info.runtime_id = (1, 11)
        snapshot = external_ai_desktop._copy_snapshot([old])
        self.assertEqual(
            external_ai_desktop._new_copy_controls([new], snapshot),
            [new],
        )

    def test_provider_404_message_is_not_returned_as_an_answer(self):
        answer = external_ai_desktop._new_text_answer(
            [],
            ["Request failed with status 404"],
            "为什么猫会呼噜？",
        )
        self.assertEqual(answer, "")

    def test_copy_failure_falls_back_without_raising(self):
        with patch.object(
            external_ai_desktop,
            "_read_clipboard_text",
            side_effect=OverflowError("pointer"),
        ):
            self.assertEqual(external_ai_desktop._invoke_copy_and_read(Mock()), "")

    def test_background_restores_previous_window_without_minimizing_early(self):
        window = Mock(handle=202)
        with patch.object(
            external_ai_desktop,
            "_activate_window_handle",
            return_value=True,
        ) as activated:
            minimized = external_ai_desktop._background_after_send(window, 101)
        self.assertFalse(minimized)
        activated.assert_called_once_with(101)
        window.minimize.assert_not_called()

    def test_browser_window_is_not_mistaken_for_desktop(self):
        window = Mock()
        window.window_text.return_value = "ChatGPT"
        window.process_id.return_value = 41
        with patch.object(
            external_ai_desktop,
            "_process_image_name",
            return_value="msedge.exe",
        ):
            self.assertFalse(external_ai_desktop._is_chatgpt_window(window))

    def test_wait_for_prompt_allows_the_desktop_webview_to_finish_loading(self):
        Desktop = Mock()
        window = Mock()
        editor = Mock()
        with (
            patch.object(
                external_ai_desktop,
                "_chatgpt_windows",
                return_value=[window],
            ),
            patch.object(
                external_ai_desktop,
                "_find_prompt_control",
                side_effect=[None, editor],
            ),
            patch.object(external_ai_desktop, "_login_required", return_value=False),
            patch.object(external_ai_desktop.time, "sleep"),
        ):
            selected, control, status = external_ai_desktop._wait_for_prompt(
                Desktop, window, timeout_seconds=1
            )
        self.assertIs(selected, window)
        self.assertIs(control, editor)
        self.assertEqual(status, "READY")

    def test_composer_utility_bar_is_never_treated_as_message_input(self):
        window = Mock()
        window_rect = Mock()
        window_rect.bottom = 900
        window_rect.top = 0
        window_rect.width.return_value = 1200
        window.rectangle.return_value = window_rect
        toolbar = Mock()
        toolbar.window_text.return_value = "Composer utility bar"
        toolbar.is_visible.return_value = True
        toolbar.is_enabled.return_value = True
        toolbar.element_info.automation_id = "composer-utility-bar"
        toolbar.element_info.control_type = "Group"
        with patch.object(
            external_ai_desktop,
            "_descendants",
            side_effect=lambda _window, kind: [toolbar] if kind == "Group" else [],
        ):
            self.assertIsNone(external_ai_desktop._find_prompt_control(window))

    def test_missing_main_composer_falls_through_to_companion(self):
        Desktop = Mock()
        keyboard = Mock()
        main = Mock()
        companion = Mock()
        with (
            patch.object(external_ai_desktop.sys, "platform", "win32"),
            patch.object(external_ai_desktop, "_load_uia", return_value=(Desktop, keyboard)),
            patch.object(external_ai_desktop, "_find_chatgpt_window", return_value=main),
            patch.object(external_ai_desktop, "_focus_window", return_value=True),
            patch.object(
                external_ai_desktop,
                "_wait_for_prompt",
                return_value=(main, None, "NOT_FOUND"),
            ),
            patch.object(
                external_ai_desktop,
                "_open_companion",
                return_value=(companion, None, "FOCUSED_ONLY"),
            ) as opened,
            patch.object(external_ai_desktop, "_accessible_texts", return_value=[]),
            patch.object(external_ai_desktop, "_buttons_named", return_value=[]),
            patch.object(external_ai_desktop, "_enter_focused_companion", return_value=True),
            patch.object(external_ai_desktop, "_foreground_window_handle", return_value=101),
            patch.object(external_ai_desktop, "_background_after_send", return_value=False),
            patch.object(external_ai_desktop, "_minimize_after_read"),
            patch.object(external_ai_desktop, "_wait_for_answer", return_value="Cats purr for several reasons."),
        ):
            result = external_ai_desktop.ask_prompt("Why do cats purr?")
        opened.assert_called_once_with(Desktop, keyboard, main)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertTrue(result["prompt_sent"])

    def test_companion_window_must_be_a_distinct_chatgpt_window(self):
        Desktop = Mock()
        keyboard = Mock()
        main = Mock(handle=10)
        companion = Mock(handle=11)
        editor = Mock()
        main_rect = Mock()
        main_rect.width.return_value = 1200
        main_rect.height.return_value = 900
        companion_rect = Mock()
        companion_rect.width.return_value = 700
        companion_rect.height.return_value = 500
        main.rectangle.return_value = main_rect
        companion.rectangle.return_value = companion_rect
        with (
            patch.object(
                external_ai_desktop,
                "_chatgpt_windows",
                side_effect=[[main], [main, companion]],
            ),
            patch.object(external_ai_desktop, "_focus_window", return_value=True),
            patch.object(
                external_ai_desktop,
                "_find_prompt_control",
                side_effect=lambda window: editor if window is companion else None,
            ),
        ):
            selected, control, status = external_ai_desktop._open_companion(
                Desktop, keyboard, main, timeout_seconds=1
            )
        keyboard.send_keys.assert_called_once_with("%{SPACE}", pause=0.05)
        self.assertIs(selected, companion)
        self.assertIs(control, editor)
        self.assertEqual(status, "READY")


if __name__ == "__main__":
    unittest.main()
