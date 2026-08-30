from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_runtime():
    requests_stub = types.ModuleType("requests")

    class RequestException(Exception):
        def __init__(self, *args, response=None):
            super().__init__(*args)
            self.response = response

    class ConnectionError(RequestException):
        pass

    class Timeout(RequestException):
        pass

    requests_stub.RequestException = RequestException
    requests_stub.ConnectionError = ConnectionError
    requests_stub.Timeout = Timeout
    requests_stub.get = lambda *_a, **_k: None
    requests_stub.post = lambda *_a, **_k: None
    spec = importlib.util.spec_from_file_location(
        "model_runtime_under_test", PROJECT_ROOT / "model_runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"requests": requests_stub}):
        spec.loader.exec_module(module)
    return module


class ModelRuntimeBudgetTests(unittest.TestCase):
    def test_large_model_is_remapped_to_12b(self):
        module = _load_runtime()
        self.assertEqual(module._normalize_model("gpt-oss:20b"), "gemma4:12b")

    def test_12b_context_is_bounded(self):
        module = _load_runtime()
        self.assertEqual(
            module._bounded_options("gemma4:12b", 16384, 9000),
            (8192, 4096),
        )

    def test_gemma4_low_thinking_preserves_fast_existing_behavior(self):
        module = _load_runtime()
        self.assertIs(module._normalize_thinking("gemma4:12b", "low"), False)
        self.assertIs(module._normalize_thinking("gemma4:12b", False), False)
        self.assertIs(module._normalize_thinking("gemma4:12b", "high"), True)
        self.assertIs(module._normalize_thinking("gemma4:12b", True), True)

    def test_gemma4_e4b_uses_compact_budget(self):
        module = _load_runtime()
        self.assertEqual(
            module._bounded_options("gemma4:e4b", 16384, 9000),
            (4096, 2048),
        )

    def test_native_system_prompt_is_sent_separately(self):
        module = _load_runtime()
        payloads = []

        @contextmanager
        def unlocked():
            yield

        with patch.object(module, "_serialized_runtime", unlocked), patch.object(
            module, "_unload_other_models", return_value=None
        ), patch.object(
            module,
            "_request",
            side_effect=lambda payload: payloads.append(payload) or "ok",
        ):
            result = module.generate(
                "CURRENT REQUEST",
                model_name="gemma4:12b",
                system_prompt="SYSTEM RULES",
                think="low",
            )
        self.assertEqual(result, "ok")
        self.assertEqual(payloads[0]["prompt"], "CURRENT REQUEST")
        self.assertEqual(payloads[0]["system"], "SYSTEM RULES")
        self.assertIs(payloads[0]["think"], False)

    def test_utf8_compaction_keeps_both_ends(self):
        module = _load_runtime()
        prompt = "RULES:" + ("规则" * 10000) + ":CURRENT QUESTION"
        compacted = module._truncate_utf8_middle(prompt, 12000)
        self.assertLessEqual(len(compacted.encode("utf-8")), 12000)
        self.assertTrue(compacted.startswith("RULES:"))
        self.assertTrue(compacted.endswith(":CURRENT QUESTION"))

    def test_recoverable_timeout_retries_once_with_reduced_budget(self):
        module = _load_runtime()
        payloads = []

        @contextmanager
        def unlocked():
            yield

        def fake_request(payload):
            payloads.append(payload)
            if len(payloads) == 1:
                raise module.requests.Timeout("CUDA runner stopped")
            return "ok"

        with patch.object(module, "_serialized_runtime", unlocked), patch.object(
            module, "_unload_other_models", return_value=None
        ), patch.object(module, "_request", side_effect=fake_request), patch.object(
            module, "_raw_unload", return_value=None
        ), patch.object(
            module, "wait_for_model_unloaded", return_value=True
        ), patch.object(module.time, "sleep", return_value=None):
            result = module.generate(
                "x" * 30000,
                num_ctx=8192,
                num_predict=3000,
                model_name="gemma4:12b",
            )
        self.assertEqual(result, "ok")
        self.assertEqual(len(payloads), 2)
        self.assertLessEqual(payloads[1]["options"]["num_ctx"], 4096)
        self.assertLessEqual(payloads[1]["options"]["num_predict"], 1024)

    def test_second_failure_stops_after_one_retry(self):
        module = _load_runtime()

        @contextmanager
        def unlocked():
            yield

        with patch.object(module, "_serialized_runtime", unlocked), patch.object(
            module, "_unload_other_models", return_value=None
        ), patch.object(
            module, "_request", side_effect=module.requests.Timeout("CUDA failed")
        ) as request, patch.object(
            module, "_raw_unload", return_value=None
        ), patch.object(
            module, "wait_for_model_unloaded", return_value=True
        ), patch.object(module.time, "sleep", return_value=None):
            with self.assertRaises(module.OllamaRuntimeError):
                module.generate("hello", model_name="gemma4:12b")
        self.assertEqual(request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
