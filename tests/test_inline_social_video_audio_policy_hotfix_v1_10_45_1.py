import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = (ROOT / "ui.py").read_text(encoding="utf-8")
FLAG = "--autoplay-policy=no-user-gesture-required"


def policy_function(platform="win32", initial=""):
    tree = ast.parse(UI_SOURCE)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_enable_inline_webview2_audio_policy"
    )

    class FakeOS:
        environ = {}

    class FakeSys:
        pass

    FakeOS.environ = {}
    if initial:
        FakeOS.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = initial
    FakeSys.platform = platform
    namespace = {
        "os": FakeOS,
        "sys": FakeSys,
        "WEBVIEW2_AUDIO_AUTOPLAY_FLAG": FLAG,
    }
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), "ui.py", "exec"),
        namespace,
    )
    return namespace["_enable_inline_webview2_audio_policy"], FakeOS.environ


class InlineSocialVideoAudioPolicyHotfixV110451Tests(unittest.TestCase):
    def test_windows_policy_is_appended_without_overwriting_existing_flags(self):
        enable, environment = policy_function(
            initial="--disable-features=ExampleFeature"
        )
        self.assertTrue(enable())
        arguments = environment["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"].split()
        self.assertIn("--disable-features=ExampleFeature", arguments)
        self.assertIn(FLAG, arguments)

    def test_policy_configuration_is_idempotent(self):
        enable, environment = policy_function(initial=FLAG)
        self.assertTrue(enable())
        self.assertTrue(enable())
        self.assertEqual(
            environment["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"].split().count(FLAG),
            1,
        )

    def test_non_windows_runtime_is_unchanged(self):
        enable, environment = policy_function(platform="linux", initial="--keep")
        self.assertFalse(enable())
        self.assertEqual(
            environment["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"],
            "--keep",
        )

    def test_policy_is_set_before_qtwebview2_is_imported(self):
        policy_call = UI_SOURCE.index(
            "INLINE_WEBVIEW2_AUDIO_POLICY_ENABLED = _enable_inline_webview2_audio_policy()"
        )
        backend_import = UI_SOURCE.index("from qtwebview2 import QtWebView2Widget")
        self.assertLess(policy_call, backend_import)
        self.assertIn("[INLINE VIDEO AUDIO POLICY]", UI_SOURCE)

    def test_audio_state_is_rechecked_after_slow_iframe_startup(self):
        self.assertIn('enable_audio("player_loaded_250ms")', UI_SOURCE)
        self.assertIn('enable_audio("player_loaded_1000ms")', UI_SOURCE)
        self.assertIn('enable_audio("player_loaded_2500ms")', UI_SOURCE)

    def test_ui_runtime_mirror_matches(self):
        self.assertEqual(
            (ROOT / "ui.py").read_bytes(),
            (ROOT / "casper" / "ui.py").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()

