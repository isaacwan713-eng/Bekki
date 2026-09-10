from pathlib import Path
from urllib.parse import parse_qs, urlparse
import unittest

import social_video


ROOT = Path(__file__).resolve().parents[1]


def call_wsgi(app, path, method="GET", scheme="https", server_name=None):
    response = {}

    def start_response(status, headers):
        response["status"] = status
        response["headers"] = dict(headers)

    body = b"".join(
        app(
            {
                "REQUEST_METHOD": method,
                "wsgi.url_scheme": scheme,
                "SERVER_NAME": server_name or social_video.WEBVIEW_WRAPPER_HOST,
                "PATH_INFO": path,
                "QUERY_STRING": "",
            },
            start_response,
        )
    )
    return response, body


class InlineSocialVideoWebView2V11044Tests(unittest.TestCase):
    def setUp(self):
        self.contract = social_video.social_video_contract(
            "https://www.youtube.com/shorts/CkrvP8IVWSE"
        )

    def test_youtube_identity_matches_the_virtual_parent_origin(self):
        parsed = urlparse(self.contract["embed_url"])
        query = parse_qs(parsed.query)
        self.assertEqual(query["origin"], [social_video.WEBVIEW_WRAPPER_ORIGIN])
        self.assertEqual(
            query["widget_referrer"],
            [social_video.WEBVIEW_WRAPPER_ORIGIN + "/"],
        )
        self.assertEqual(
            social_video.webview_wrapper_url(self.contract),
            "https://bekki-video.local/player/youtube/CkrvP8IVWSE",
        )

    def test_wsgi_app_serves_only_the_exact_verified_https_path(self):
        app = social_video.webview_wsgi_app(self.contract)
        path = urlparse(social_video.webview_wrapper_url(self.contract)).path
        response, body = call_wsgi(app, path)
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(response["headers"]["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(response["headers"]["X-Content-Type-Options"], "nosniff")
        self.assertIn(b'id="bekki-inline-player"', body)
        self.assertIn(b"Content-Security-Policy", body)
        self.assertIn(b"referrerpolicy", body)

        for candidate in (
            ("/player/youtube/another1234", "GET", "https", None),
            (path, "POST", "https", None),
            (path, "GET", "http", None),
            (path, "GET", "https", "evil.example"),
        ):
            with self.subTest(candidate=candidate):
                rejected, rejected_body = call_wsgi(
                    app,
                    candidate[0],
                    method=candidate[1],
                    scheme=candidate[2],
                    server_name=candidate[3],
                )
                self.assertEqual(rejected["status"], "404 Not Found")
                self.assertEqual(rejected_body, b"Not Found")

    def test_tampering_and_navigation_fail_closed(self):
        tampered = dict(self.contract)
        tampered["embed_url"] = "https://evil.example/player"
        self.assertEqual(social_video.webview_wrapper_url(tampered), "")
        self.assertIsNone(social_video.webview_wsgi_app(tampered))

        wrapper_url = social_video.webview_wrapper_url(self.contract)
        self.assertTrue(
            social_video.allowed_webview_navigation(wrapper_url, self.contract)
        )
        self.assertTrue(
            social_video.allowed_webview_navigation(
                self.contract["embed_url"], self.contract
            )
        )
        self.assertTrue(
            social_video.allowed_webview_navigation("about:blank", self.contract)
        )
        self.assertFalse(
            social_video.allowed_webview_navigation(
                wrapper_url + "?escape=1", self.contract
            )
        )
        self.assertFalse(
            social_video.allowed_webview_navigation(
                "https://www.youtube.com/watch?v=CkrvP8IVWSE", self.contract
            )
        )

    def test_ui_uses_one_lazy_edge_backend_and_blocks_escape_paths(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("from qtwebview2 import QtWebView2Widget", source)
        self.assertIn('"handle_new_window": False', source)
        self.assertIn('"lazyload": True', source)
        self.assertIn(
            '"user_data_folder": _inline_video_user_data_folder()', source
        )
        self.assertIn('"wsgi_app": wsgi_app', source)
        self.assertIn(
            '"init_settings_hook": self._configure_inline_webview', source
        )
        self.assertIn("core_webview.NavigationStarting +=", source)
        self.assertIn("core_webview.NewWindowRequested +=", source)
        self.assertIn("core_webview.DownloadStarting +=", source)
        self.assertIn("args.Handled = True", source)
        self.assertIn("args.Cancel = True", source)
        self.assertIn('view.load_url("about:blank")', source)
        self.assertIn('_safe_qt_call(view, "close")', source)
        self.assertNotIn("QWebEngine", source)
        self.assertNotIn("[INLINE VIDEO CODECS]", source)

    def test_windows_dependency_and_installer_are_pinned(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        installer = (ROOT / "INSTALL_STABLE_V1.ps1").read_text(encoding="utf-8")
        self.assertIn("qtwebview2==0.5.0", requirements)
        self.assertIn("pythonnet>=3.0,<4", requirements)
        self.assertIn('& $python -c "import qtwebview2"', installer)
        self.assertIn('& $python -m pip install "qtwebview2==0.5.0"', installer)

    def test_packaging_collects_webview2_runtime_files(self):
        for relative_path in ("Bekki.spec", "casper/Bekki.spec"):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("from PyInstaller.utils.hooks import collect_all", source)
            self.assertIn("qtwebview2_datas", source)
            self.assertIn("qtwebview2_binaries", source)
            self.assertIn("qtwebview2_hiddenimports", source)
            self.assertNotIn("PySide6.QtWebEngine", source)

    def test_runtime_player_mirrors_match(self):
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
