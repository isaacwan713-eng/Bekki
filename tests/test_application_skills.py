import json
import os
import tempfile
import types
import unittest
from unittest.mock import patch

from casper import application_skills


class ApplicationSkillMemoryTests(unittest.TestCase):
    def test_verified_application_identity_is_learned_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "application_skills.json")
            with patch.dict(
                os.environ,
                {"BEKKI_APP_SKILLS_PATH": path},
                clear=False,
            ):
                saved = application_skills.remember_application(
                    "Steam",
                    name="Steam",
                    app_id=r"{GUID}\Steam\Steam.exe",
                    shortcut_path=r"C:\Start Menu\Steam.lnk",
                    launch_route="apps_folder",
                )
                learned = application_skills.get_application("steam")
                with open(path, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)
        self.assertTrue(saved)
        self.assertEqual(learned["name"], "Steam")
        self.assertEqual(learned["app_id"], r"{GUID}\Steam\Steam.exe")
        self.assertEqual(raw["schema_version"], 1)
        self.assertEqual(raw["steam_games"], {})

    def test_skill_lookup_is_exact_not_fuzzy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "application_skills.json")
            with patch.dict(
                os.environ,
                {"BEKKI_APP_SKILLS_PATH": path},
                clear=False,
            ):
                application_skills.remember_application(
                    "Steam",
                    name="Steam",
                    app_id="steam.app",
                )
                self.assertIsNone(
                    application_skills.get_application("Steam Support Center")
                )

    def test_invalid_registry_fails_closed_and_can_recover(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "application_skills.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("not json")
            with patch.dict(
                os.environ,
                {"BEKKI_APP_SKILLS_PATH": path},
                clear=False,
            ):
                self.assertIsNone(application_skills.get_application("Steam"))
                self.assertTrue(
                    application_skills.remember_application(
                        "Steam",
                        name="Steam",
                        shortcut_path=r"C:\Start Menu\Steam.lnk",
                    )
                )
                self.assertEqual(
                    application_skills.get_application("Steam")["name"],
                    "Steam",
                )

    def test_verified_steam_game_alias_is_learned_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "application_skills.json")
            with patch.dict(
                os.environ,
                {"BEKKI_APP_SKILLS_PATH": path},
                clear=False,
            ):
                saved = application_skills.remember_steam_game(
                    "FM26",
                    name="Football Manager 2026",
                    app_id="123456",
                    launch_route="steam_manifest",
                )
                learned = application_skills.get_steam_game("FM26")
        self.assertTrue(saved)
        self.assertEqual(learned["name"], "Football Manager 2026")
        self.assertEqual(learned["app_id"], "123456")

    def test_ai_resolves_vs_code_from_bounded_candidate_names(self):
        captured = {}

        def run_ai_prompt(_prompt, input_text, **kwargs):
            captured["input"] = json.loads(input_text)
            captured["kwargs"] = kwargs
            return {
                "candidate_index": 1,
                "confidence": "high",
                "reason": "common alias",
            }

        fake_tools = types.SimpleNamespace(run_ai_prompt=run_ai_prompt)
        candidates = [
            {"name": "Visual Studio Code", "app_id": "vscode.app"},
            {"name": "Microsoft Edge", "app_id": "edge.app"},
        ]
        with patch.dict("sys.modules", {"tools": fake_tools}):
            selected = application_skills.select_installed_candidate(
                "VS Code",
                candidates,
                "application",
            )
        self.assertEqual(selected["name"], "Visual Studio Code")
        self.assertNotIn("app_id", captured["input"]["candidates"][0])
        self.assertEqual(captured["kwargs"]["model_name"], "llama3.2:latest")

    def test_ai_low_confidence_never_selects_an_installed_candidate(self):
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=lambda *_args, **_kwargs: {
                "candidate_index": 1,
                "confidence": "low",
                "reason": "ambiguous",
            }
        )
        with patch.dict("sys.modules", {"tools": fake_tools}):
            selected = application_skills.select_installed_candidate(
                "editor",
                [{"name": "Visual Studio Code", "app_id": "vscode.app"}],
                "application",
            )
        self.assertIsNone(selected)

    def test_ai_can_resolve_chinese_genshin_name_without_receiving_app_id(self):
        captured = {}

        def run_ai_prompt(_prompt, input_text, **_kwargs):
            captured["input"] = json.loads(input_text)
            return {
                "candidate_index": 1,
                "confidence": "high",
                "reason": "原神 is the Chinese name for Genshin Impact",
            }

        fake_tools = types.SimpleNamespace(run_ai_prompt=run_ai_prompt)
        candidates = [
            {"name": "Genshin Impact", "app_id": "genshin.app"},
            {"name": "HoYoPlay", "app_id": "hoyoplay.app"},
        ]
        with patch.dict("sys.modules", {"tools": fake_tools}):
            selected = application_skills.select_installed_candidate(
                "原神",
                candidates,
                "application",
            )
        self.assertEqual(selected["name"], "Genshin Impact")
        self.assertEqual(
            [row["name"] for row in captured["input"]["candidates"]],
            ["Genshin Impact", "HoYoPlay"],
        )
        self.assertNotIn("app_id", captured["input"]["candidates"][0])

    def test_invalid_small_model_candidate_output_retries_with_12b(self):
        calls = []
        unloaded = []

        def run_ai_prompt(prompt_path, _input_text, **kwargs):
            calls.append((prompt_path, kwargs))
            if len(calls) == 1:
                return None
            return {
                "candidate_index": 1,
                "confidence": "high",
                "reason": "原神 is Genshin Impact",
            }

        fake_tools = types.SimpleNamespace(
            run_ai_prompt=run_ai_prompt,
            unload_model=lambda model_name: unloaded.append(model_name),
        )
        candidates = [
            {"name": "Genshin Impact", "app_id": "genshin.app"},
            {"name": "HoYoPlay", "app_id": "hoyoplay.app"},
        ]
        with patch.dict("sys.modules", {"tools": fake_tools}):
            selected = application_skills.select_installed_candidate(
                "原神",
                candidates,
                "application",
            )
        self.assertEqual(selected["name"], "Genshin Impact")
        self.assertEqual(
            [call[1]["model_name"] for call in calls],
            ["llama3.2:latest", "gemma3:12b"],
        )
        self.assertTrue(calls[0][1]["json_schema"])
        self.assertIn("recover", calls[1][0])
        self.assertEqual(unloaded, ["llama3.2:latest"])

    def test_installed_steam_manifests_are_discovered_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            steamapps = os.path.join(directory, "steamapps")
            os.makedirs(steamapps)
            manifest = os.path.join(steamapps, "appmanifest_123456.acf")
            with open(manifest, "w", encoding="utf-8") as handle:
                handle.write(
                    '"AppState"\n{\n"appid" "123456"\n'
                    '"name" "Football Manager 2026"\n}\n'
                )
            with patch.object(application_skills.os, "name", "nt"), patch.object(
                application_skills,
                "_steam_root_candidates",
                return_value=[directory],
            ):
                games = application_skills.discover_steam_games()
        self.assertEqual(
            games,
            [{"name": "Football Manager 2026", "app_id": "123456"}],
        )
