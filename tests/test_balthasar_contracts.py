import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


def _load_balthasar():
    path = Path(__file__).resolve().parents[1] / "balthasar.py"
    spec = importlib.util.spec_from_file_location("balthasar_under_test", path)
    module = importlib.util.module_from_spec(spec)
    tools_stub = types.SimpleNamespace(run_ai_prompt=lambda *_a, **_k: None)
    with patch.dict(sys.modules, {"tools": tools_stub}):
        spec.loader.exec_module(module)
    return module


class BalthasarContractTests(unittest.TestCase):
    def test_primary_router_prompt_has_no_pipe_separated_enum_template(self):
        prompt = (
            Path(__file__).resolve().parents[1]
            / "prompts"
            / "balthasar_router.txt"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"neutral|happy', prompt)
        self.assertIn("Choose exactly one value", prompt)

    def test_emotion_router_retries_invalid_json_with_distinct_contract(self):
        balthasar = _load_balthasar()
        valid = {
            "user_emotion": "neutral",
            "intensity": 0.1,
            "tone": "warm",
            "support_style": "direct",
            "bekki_mood": "concerned",
            "valence_delta": 0,
            "energy_delta": 0,
            "closeness_delta": 0,
            "reason": "routine",
        }
        with patch.object(
            balthasar.tools, "run_ai_prompt", side_effect=[None, valid]
        ) as model:
            result = balthasar.plan_response(
                "打开内容文件夹", "", '{"mood":"concerned"}'
            )
        self.assertEqual(result["bekki_mood"], "concerned")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/balthasar_router_retry.txt",
        )
        self.assertEqual(model.call_args_list[1].kwargs["num_predict"], 1800)

    def test_emotion_router_retries_pipe_separated_schema_placeholders(self):
        balthasar = _load_balthasar()
        placeholder = {
            "user_emotion": "tired | frustrated | anxious",
            "intensity": 0.5,
            "tone": "calm | serious | playful",
            "support_style": "grounding | comforting | encouraging",
            "bekki_mood": "concerned",
            "reason": "copied schema",
        }
        valid = {
            "user_emotion": "tired",
            "intensity": 0.6,
            "tone": "calm",
            "support_style": "comforting",
            "bekki_mood": "concerned",
            "valence_delta": -0.02,
            "energy_delta": -0.03,
            "closeness_delta": 0.005,
            "reason": "The user said work was exhausting.",
        }
        with patch.object(
            balthasar.tools, "run_ai_prompt", side_effect=[placeholder, valid]
        ) as model:
            result = balthasar.plan_response(
                "今天工作好累，陪我聊一会儿吧", "", '{"mood":"curious"}'
            )
        self.assertEqual(result["user_emotion"], "tired")
        self.assertEqual(result["tone"], "calm")
        self.assertEqual(result["support_style"], "comforting")
        self.assertEqual(model.call_count, 2)

    def test_calibration_retries_and_preserves_high_risk_boundary(self):
        balthasar = _load_balthasar()
        valid = {
            "execution_style": "fast",
            "confirmation_sensitivity": "normal",
            "preferred_sources": [],
            "user_constraints": [],
            "presentation_preferences": [],
            "reason": "explicit preference",
        }
        with patch.object(
            balthasar.tools, "run_ai_prompt", side_effect=[None, valid]
        ) as model:
            result = balthasar.calibrate_execution(
                "request", {"risk": "high"}, {}, ""
            )
        self.assertEqual(result["execution_style"], "fast")
        self.assertEqual(result["confirmation_sensitivity"], "elevated")
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/balthasar_calibrate_retry.txt",
        )


if __name__ == "__main__":
    unittest.main()
