import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_magi(ai_outputs):
    outputs = list(ai_outputs)
    calls = []

    def run_ai_prompt(*args, **kwargs):
        calls.append((args, kwargs))
        return outputs.pop(0)

    tools_stub = types.SimpleNamespace(
        run_ai_prompt=run_ai_prompt,
        unload_model=lambda *_args, **_kwargs: None,
    )
    spec = importlib.util.spec_from_file_location(
        "magi_under_test", PROJECT_ROOT / "magi.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"tools": tools_stub}):
        spec.loader.exec_module(module)
    module._test_ai_calls = calls
    return module


def _load_melchior():
    stubs = {
        "context": types.SimpleNamespace(load_context=lambda: {}),
        "document": types.SimpleNamespace(has_document=lambda: False),
        "memory": types.SimpleNamespace(
            initialize_memory=lambda: {},
            get_long_term_context=lambda _data: "",
        ),
        "magi": types.SimpleNamespace(
            audit_route=lambda *_a, previous_route=None, **_k: previous_route,
        ),
        "tools": types.SimpleNamespace(
            run_ai_prompt=lambda *_a, **_k: None,
            unload_model=lambda *_a, **_k: None,
        ),
        "vision": types.SimpleNamespace(has_image=lambda: False),
    }
    spec = importlib.util.spec_from_file_location(
        "melchior_stable_v1_under_test", PROJECT_ROOT / "melchior.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


class MagiLaneTests(unittest.TestCase):
    def test_gate_contract_routes_reminder_listing_to_command(self):
        prompt = (PROJECT_ROOT / "prompts" / "magi_gate.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn('"我有哪些提醒" -> COMMAND', prompt)
        self.assertIn("Read-only inspection is still COMMAND", prompt)

    def test_gate_contract_assigns_explicit_xiaohongshu_search_to_social(self):
        prompt = (PROJECT_ROOT / "prompts" / "magi_gate.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("social_scope SOCIAL_RESEARCH", prompt)
        self.assertIn('["xiaohongshu"]', prompt)
        self.assertIn('"去小红书搜索美国麦当劳新出的玩具"', prompt)
        self.assertIn("not RECOMMENDATION_RESEARCH + PRODUCT", prompt)

    def test_social_product_conflict_gets_targeted_ai_recovery(self):
        contradictory = {
            "lane": "SEARCH",
            "confidence": 0.95,
            "reason": "The user explicitly requests Xiaohongshu toy posts.",
            "social_scope": "SOCIAL_RESEARCH",
            "social_platforms": ["xiaohongshu"],
            "search_scope": "RECOMMENDATION_RESEARCH",
            "recommendation_domain": "PRODUCT",
        }
        repaired = {
            **contradictory,
            "search_scope": "SOCIAL_RESEARCH",
            "recommendation_domain": None,
        }
        module = _load_magi([contradictory, repaired])
        result = module.route_request("去小红书搜索美国麦当劳新出的玩具")
        self.assertEqual(result["source"], "ai_recovery")
        self.assertEqual(result["search_scope"], "SOCIAL_RESEARCH")
        self.assertIsNone(result["recommendation_domain"])
        retry_packet = module._test_ai_calls[1][0][1]
        self.assertIn("search_scope must also be SOCIAL_RESEARCH", retry_packet)
        self.assertIn("recommendation_domain must be null", retry_packet)

    def test_gate_contract_distinguishes_restaurant_recommendation_from_news(self):
        prompt = (PROJECT_ROOT / "prompts" / "magi_gate.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn('"推荐几家圣盖博好吃的中餐厅"', prompt)
        self.assertIn('"圣盖博地区有什么好吃的中餐厅"', prompt)
        self.assertIn("recommendation_domain RESTAURANT, never NEWS_FEED", prompt)

    def test_reliable_gate_preserves_social_platform_contract(self):
        module = _load_magi([{
            "lane": "SEARCH",
            "confidence": 0.98,
            "reason": "The user explicitly requested Xiaohongshu posts.",
            "social_scope": "SOCIAL_RESEARCH",
            "social_platforms": ["xiaohongshu"],
        }])
        result = module.route_request(
            "去小红书搜索最近一周 Arcadia 亲子餐厅推荐"
        )
        self.assertEqual(result["lane"], "SEARCH")
        self.assertEqual(result["social_scope"], "SOCIAL_RESEARCH")
        self.assertEqual(result["social_platforms"], ["xiaohongshu"])
        schema = module._test_ai_calls[0][1]["json_schema"]
        self.assertIn("social_scope", schema["required"])
        self.assertIn("social_platforms", schema["required"])

    def test_reliable_gate_preserves_restaurant_recommendation_contract(self):
        module = _load_magi([{
            "lane": "SEARCH",
            "confidence": 0.98,
            "reason": "The user wants good local restaurants worth choosing.",
            "social_scope": "OTHER",
            "social_platforms": [],
            "search_scope": "RECOMMENDATION_RESEARCH",
            "recommendation_domain": "RESTAURANT",
        }])
        result = module.route_request("推荐几家圣盖博好吃的中餐厅")
        self.assertEqual(result["lane"], "SEARCH")
        self.assertEqual(result["search_scope"], "RECOMMENDATION_RESEARCH")
        self.assertEqual(result["recommendation_domain"], "RESTAURANT")
        schema = module._test_ai_calls[0][1]["json_schema"]
        self.assertIn("search_scope", schema["required"])
        self.assertIn("recommendation_domain", schema["required"])

    def test_contradictory_social_contract_gets_ai_recovery(self):
        module = _load_magi([
            {
                "lane": "SEARCH",
                "confidence": 0.98,
                "reason": "Explicit social research.",
                "social_scope": "SOCIAL_RESEARCH",
                "social_platforms": [],
            },
            {
                "lane": "SEARCH",
                "confidence": 0.97,
                "reason": "Explicit Xiaohongshu research.",
                "social_scope": "SOCIAL_RESEARCH",
                "social_platforms": ["xiaohongshu"],
            },
        ])
        result = module.route_request("去小红书搜索亲子餐厅")
        self.assertEqual(result["source"], "ai_recovery")
        self.assertEqual(result["social_platforms"], ["xiaohongshu"])

    def test_recent_news_ai_result_is_search(self):
        module = _load_magi([{
            "lane": "SEARCH",
            "confidence": 0.97,
            "reason": "Current football news needs external evidence.",
        }])
        result = module.route_request("曼联最近有什么新闻？")
        self.assertEqual(result["lane"], "SEARCH")
        self.assertEqual(result["source"], "ai_primary")
        self.assertEqual(len(module._test_ai_calls), 1)

    def test_emotional_message_ai_result_is_local(self):
        result = _load_magi([{
            "lane": "LOCAL",
            "confidence": 0.96,
            "reason": "This is emotional conversation.",
        }]).route_request("我最近工作好累，陪我聊聊")
        self.assertEqual(result["lane"], "LOCAL")

    def test_open_recycle_bin_ai_result_is_command(self):
        result = _load_magi([{
            "lane": "COMMAND",
            "confidence": 0.99,
            "reason": "The requested outcome changes local computer state.",
        }]).route_request("打开回收站")
        self.assertEqual(result["lane"], "COMMAND")

    def test_python_does_not_override_ai_lane_by_keywords(self):
        result = _load_magi([{
            "lane": "LOCAL",
            "confidence": 0.75,
            "reason": "Synthetic contract test.",
        }]).route_request("新闻 搜索 打开 推荐")
        self.assertEqual(result["lane"], "LOCAL")

    def test_invalid_primary_contract_uses_second_ai(self):
        module = _load_magi([
            {"lane": "SEARCH | LOCAL", "confidence": 0.5, "reason": "bad"},
            {"lane": "COMMAND", "confidence": 0.9, "reason": "local action"},
        ])
        result = module.route_request("打开回收站")
        self.assertEqual(result["lane"], "COMMAND")
        self.assertEqual(result["source"], "ai_recovery")
        self.assertEqual(len(module._test_ai_calls), 2)

    def test_zero_confidence_primary_uses_reliable_ai_recovery(self):
        module = _load_magi([
            {"lane": "COMMAND", "confidence": 0.0, "reason": "uncertain"},
            {"lane": "LOCAL", "confidence": 0.94, "reason": "basic math"},
        ])
        result = module.route_request("1+1等于多少")
        self.assertEqual(result["lane"], "LOCAL")
        self.assertEqual(result["source"], "ai_recovery")
        self.assertEqual(
            module._test_ai_calls[0][1]["model_name"],
            "gemma3:12b",
        )
        self.assertEqual(
            module._test_ai_calls[1][1]["model_name"],
            "gemma3:4b",
        )


class MagiBoundaryTests(unittest.TestCase):
    def test_reliable_magi_restaurant_route_bypasses_compact_melchior(self):
        module = _load_melchior()
        with patch.object(
            module.tools,
            "run_ai_prompt",
            side_effect=AssertionError(
                "Reliable MAGI recommendation route must bypass compact Melchior"
            ),
        ) as model:
            plan = module.plan_request(
                "推荐几家圣盖博好吃的中餐厅",
                magi_route={
                    "lane": "SEARCH",
                    "confidence": 0.98,
                    "reason": "Restaurant recommendation request.",
                    "social_scope": "OTHER",
                    "social_platforms": [],
                    "search_scope": "RECOMMENDATION_RESEARCH",
                    "recommendation_domain": "RESTAURANT",
                },
            )
        model.assert_not_called()
        self.assertEqual(plan["response_mode"], "RECOMMENDATION_RESEARCH")
        self.assertEqual(plan["recommendation_domain"], "RESTAURANT")
        self.assertTrue(plan["needs_search"])
        self.assertEqual(plan["source_policy"], "domain_evidence")

    def test_reliable_magi_social_route_bypasses_compact_melchior(self):
        module = _load_melchior()
        with patch.object(
            module.tools,
            "run_ai_prompt",
            side_effect=AssertionError(
                "Reliable MAGI social route must bypass compact Melchior"
            ),
        ) as model:
            plan = module.plan_request(
                "去小红书搜索最近一周 Arcadia 亲子餐厅推荐",
                magi_route={
                    "lane": "SEARCH",
                    "confidence": 0.98,
                    "reason": "Explicit Xiaohongshu research.",
                    "social_scope": "SOCIAL_RESEARCH",
                    "social_platforms": ["xiaohongshu"],
                },
            )
        model.assert_not_called()
        self.assertEqual(plan["response_mode"], "SOCIAL_RESEARCH")
        self.assertEqual(plan["social_platforms"], ["xiaohongshu"])
        self.assertTrue(plan["needs_search"])
        self.assertEqual(plan["source_policy"], "platform_native")

    def test_cross_lane_audit_social_route_bypasses_second_compact_plan(self):
        module = _load_melchior()
        initial = {
            "response_mode": "LOCAL_ANSWER",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "skill_route": "none",
            "device_scope": None,
            "interaction_mode": "TASK",
            "context_profile": "MINIMAL",
            "reason": "incorrect local route",
        }
        with patch.object(
            module.tools, "run_ai_prompt", return_value=initial
        ) as model, patch.object(
            module.magi,
            "audit_route",
            return_value={
                "lane": "SEARCH",
                "confidence": 0.98,
                "reason": "Explicit Xiaohongshu research.",
                "social_scope": "SOCIAL_RESEARCH",
                "social_platforms": ["xiaohongshu"],
            },
        ) as audit:
            plan = module.plan_request(
                "去小红书搜索亲子餐厅",
                magi_route={"lane": "SEARCH", "confidence": 0.95},
            )
        self.assertEqual(model.call_count, 1)
        audit.assert_called_once()
        self.assertEqual(plan["response_mode"], "SOCIAL_RESEARCH")
        self.assertEqual(plan["social_platforms"], ["xiaohongshu"])

    def test_initial_melchior_schema_can_challenge_magi_lane(self):
        module = _load_melchior()
        schema = module._independent_router_schema()
        self.assertEqual(
            set(schema["properties"]["response_mode"]["enum"]),
            module.VALID_MODES,
        )
        self.assertIn("TASK_ACTION", schema["properties"]["response_mode"]["enum"])

    def test_search_lane_rejects_local_mode(self):
        module = _load_melchior()
        plan = module._normalize_plan({"response_mode": "LOCAL_ANSWER"})
        self.assertFalse(module._plan_matches_magi(
            plan, {"lane": "SEARCH", "confidence": 0.98}
        ))

    def test_command_lane_accepts_ai_device_mode(self):
        module = _load_melchior()
        plan = module._normalize_plan({"response_mode": "DEVICE_ACTION"})
        self.assertTrue(module._plan_matches_magi(
            plan, {"lane": "COMMAND", "confidence": 0.99}
        ))

    def test_cross_lane_route_is_redecided_by_ai(self):
        module = _load_melchior()
        initial = {
            "response_mode": "LOCAL_ANSWER",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "skill_route": "none",
            "interaction_mode": "TASK",
            "context_profile": "MINIMAL",
            "reason": "incorrect local route",
        }
        corrected = {
            **initial,
            "response_mode": "NEWS_FEED",
            "reason": "AI corrected within the SEARCH lane",
        }
        with patch.object(
            module.tools, "run_ai_prompt", side_effect=[initial, corrected]
        ) as model, patch.object(
            module.magi,
            "audit_route",
            return_value={"lane": "SEARCH", "confidence": 0.99},
        ) as audit:
            plan = module.plan_request(
                "曼联最近有什么新闻？",
                magi_route={"lane": "SEARCH", "confidence": 0.97},
            )
        self.assertEqual(plan["response_mode"], "NEWS_FEED")
        self.assertEqual(plan["magi_lane"], "SEARCH")
        self.assertEqual(model.call_count, 2)
        audit.assert_called_once()

    def test_reminder_listing_cross_lane_returns_to_reliable_magi(self):
        module = _load_melchior()
        initial = {
            "response_mode": "TASK_ACTION",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "skill_route": "none",
            "interaction_mode": "TASK",
            "context_profile": "MINIMAL",
            "reason": "Listing reminders must inspect Bekki's task store.",
        }
        corrected = dict(initial)
        with patch.object(
            module.tools, "run_ai_prompt", side_effect=[initial, corrected]
        ) as model, patch.object(
            module.magi,
            "audit_route",
            return_value={
                "lane": "COMMAND",
                "confidence": 0.99,
                "reason": "The request reads local reminder state.",
            },
        ) as audit:
            plan = module.plan_request(
                "我有哪些提醒",
                magi_route={
                    "lane": "LOCAL",
                    "confidence": 0.95,
                    "reason": "Initial route was wrong.",
                },
            )

        self.assertEqual(plan["response_mode"], "TASK_ACTION")
        self.assertEqual(plan["magi_lane"], "COMMAND")
        audit.assert_called_once()
        self.assertEqual(
            model.call_args_list[0].kwargs["json_schema"]["properties"]
            ["response_mode"]["enum"],
            sorted(module.VALID_MODES),
        )
        self.assertEqual(
            model.call_args_list[1].kwargs["json_schema"]["properties"]
            ["response_mode"]["enum"],
            sorted(module.MAGI_LANE_MODES["COMMAND"]),
        )

    def test_matching_initial_plan_does_not_audit(self):
        module = _load_melchior()
        raw = {
            "response_mode": "LOCAL_ANSWER",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "skill_route": "none",
            "interaction_mode": "TASK",
            "context_profile": "MINIMAL",
            "reason": "Basic arithmetic is a local answer.",
        }
        with patch.object(
            module.tools, "run_ai_prompt", return_value=raw
        ), patch.object(module.magi, "audit_route") as audit:
            plan = module.plan_request(
                "1+1等于多少",
                magi_route={"lane": "LOCAL", "confidence": 0.99},
            )
        self.assertEqual(plan["response_mode"], "LOCAL_ANSWER")
        audit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
