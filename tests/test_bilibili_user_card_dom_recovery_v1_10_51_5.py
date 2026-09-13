from pathlib import Path
import types
import unittest

import social_browser
from casper import browser
from nerv import knowledge_curator


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"


class BilibiliUserCardDomRecoveryTests(unittest.TestCase):
    @staticmethod
    def _current_card(**updates):
        value = {
            "url": "https://space.bilibili.com/3546863493651718",
            "visible_text": (
                "四禧丸子_Official LV6 5.3万粉丝 · 55个视频 "
                "虚拟偶像团体——四禧丸子 +关注"
            ),
            "image_url": "https://i0.hdslb.com/avatar.jpg",
            "source_kind": "generic_link",
            "dom_card_matched": True,
            "profile_result_matched": False,
            "profile_verified": False,
            "bilibili_user_search": True,
        }
        value.update(updates)
        return value

    def test_current_bilibili_user_card_signature_recovers_exact_profile(self):
        candidate = social_browser._recover_bilibili_user_profile_candidate(
            self._current_card()
        )
        self.assertTrue(candidate["profile_result_matched"])
        self.assertEqual(candidate["source_kind"], "profile_result")
        self.assertEqual(candidate["profile_name"], "四禧丸子_Official")
        proof = browser._bilibili_official_profile_proof(
            candidate, "四禧丸子"
        )
        self.assertIsNotNone(proof)
        self.assertTrue(proof["official_identity_verified"])

    def test_profile_recovery_requires_user_page_card_metrics_and_avatar(self):
        unsafe_variants = [
            {"bilibili_user_search": False},
            {"dom_card_matched": False},
            {"image_url": ""},
            {"visible_text": "普通视频 四禧丸子_Official"},
            {"url": "https://www.bilibili.com/video/BV1notaprofile"},
        ]
        for updates in unsafe_variants:
            with self.subTest(updates=updates):
                candidate = social_browser._recover_bilibili_user_profile_candidate(
                    self._current_card(**updates)
                )
                self.assertFalse(candidate.get("profile_result_matched"))

    def test_current_card_survives_profile_candidate_filter(self):
        card = self._current_card()

        class Frame:
            def evaluate(self, _script):
                return [card]

        page = types.SimpleNamespace(frames=[Frame()])
        values = social_browser._extract_post_candidates(
            page, "bilibili", include_profile_candidates=True
        )
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["source_kind"], "profile_result")
        self.assertEqual(values[0]["profile_name"], "四禧丸子_Official")

    def test_dom_fallback_requires_one_numeric_space_identity_per_card(self):
        observed = {}

        class Frame:
            def evaluate(self, script):
                observed["script"] = script
                return []

        page = types.SimpleNamespace(frames=[Frame()])
        self.assertEqual(
            social_browser._extract_post_candidates(
                page, "bilibili", include_profile_candidates=True
            ),
            [],
        )
        self.assertIn("looksLikeBilibiliProfileCard", observed["script"])
        self.assertIn("identities.size === 1", observed["script"])
        self.assertIn("bilibili_user_search", observed["script"])

    def test_similar_visible_account_still_fails_exact_identity_gate(self):
        candidate = social_browser._recover_bilibili_user_profile_candidate(
            self._current_card(
                visible_text=(
                    "四禧丸子_Artificial LV2 2粉丝 · 2个视频 +关注"
                )
            )
        )
        self.assertTrue(candidate["profile_result_matched"])
        self.assertIsNone(
            browser._bilibili_official_profile_proof(
                candidate, "四禧丸子"
            )
        )

    def test_curator_uses_single_item_isolation_after_live_cross_topic_output(self):
        self.assertEqual(knowledge_curator.MAX_BATCH_ITEMS, 1)


class BuildMetadataTests(unittest.TestCase):
    def test_build_id(self):
        text = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('BEKKI_BUILD_ID = "' + BUILD_ID + '"', text)


if __name__ == "__main__":
    unittest.main()
