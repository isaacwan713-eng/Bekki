import unittest
from pathlib import Path
from unittest.mock import patch

from casper import content_recommendation, content_workflow


class ContentRecommendationTests(unittest.TestCase):
    def test_stage_prompts_make_standalone_current_request_authoritative(self):
        prompt_root = Path(content_workflow.__file__).resolve().parent.parent / "prompts"
        for name in (
            "casper_content_stage.txt",
            "casper_content_authorized_stage.txt",
        ):
            text = (prompt_root / name).read_text(encoding="utf-8")
            self.assertIn("CURRENT_REQUEST has priority", text)
            self.assertIn("OPEN_FOLDER_ONLY even", text)

    def test_folder_only_stage_never_runs_recommendation_or_pending_install(self):
        folder = {
            "success": True,
            "completed": True,
            "action": "folder_skill_awaiting_user_verification",
            "requires_user_verification": True,
        }
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="OPEN_FOLDER_ONLY",
        ), patch(
            "casper.skill_registry.match_pending_resume", return_value=None
        ) as pending, patch(
            "casper.skill_registry.match_verified", return_value=None
        ), patch(
            "casper.content_learning.execute", return_value=folder
        ) as learn, patch(
            "casper.content_recommendation.execute"
        ) as recommend:
            result = content_workflow.execute(
                "打开 FM26 战术文件夹",
                "",
                content_authorized=True,
                skill_lookup_requested=True,
            )
        self.assertEqual(result, folder)
        pending.assert_not_called()
        recommend.assert_not_called()
        self.assertEqual(
            learn.call_args.kwargs["requested_skill_scope"],
            "OPEN_DESTINATION_FOLDER",
        )

    def _pages(self):
        return [
            {
                "id": "source-" + str(index),
                "title": "Tactic " + str(index),
                "domain": "source" + str(index) + ".test",
                "url": "https://source" + str(index) + ".test/tactic",
                "content": "Dedicated tested FM26 tactic page " + str(index),
            }
            for index in range(1, 4)
        ]

    def test_ai_recommendations_keep_exact_browser_urls_and_open_best(self):
        pages = self._pages()
        plan = {"target_app": "FM26", "content_kind": "tactic"}
        model_result = {
            "recommendations": [
                {
                    "source_id": page["id"],
                    "title": page["title"],
                    "summary": "Evidence-backed option " + str(index),
                    "formation": "4-2-3-1",
                    "fit_reason": "Fits the requested squad",
                    "evidence": "Visible test evidence",
                    "url": "https://invented.invalid/file",
                }
                for index, page in enumerate(pages, start=1)
            ],
            "open_source_id": "source-2",
        }
        with patch.object(
            content_recommendation.content_research, "_plan", return_value=plan
        ), patch.object(
            content_recommendation.content_research,
            "_review_queries",
            return_value=plan,
        ), patch.object(
            content_recommendation.content_research,
            "_discover",
            return_value=([{"id": "source"}], None),
        ), patch.object(
            content_recommendation.content_research,
            "_rank_discovered",
            return_value=[{"id": "source"}],
        ), patch.object(
            content_recommendation.content_research,
            "_read_candidates",
            return_value=pages,
        ), patch.object(
            content_recommendation.content_research,
            "_ai",
            return_value=model_result,
        ), patch.object(
            content_recommendation.browser,
            "open_human_handoff",
            return_value=True,
        ) as opened:
            result = content_recommendation.execute("推荐三个 FM26 战术", "")
        self.assertEqual(result["recommendation_count"], 3)
        self.assertEqual(
            [card["url"] for card in result["cards"]],
            [page["url"] for page in pages],
        )
        self.assertNotIn("invented.invalid", str(result))
        opened.assert_called_once_with(pages[1]["url"])

    def test_invented_source_id_cannot_become_a_card(self):
        with patch.object(
            content_recommendation.content_research,
            "_ai",
            return_value={
                "recommendations": [{
                    "source_id": "invented-id",
                    "title": "Invented",
                    "summary": "Invented",
                }],
                "open_source_id": "invented-id",
            },
        ):
            recommendations, opened = content_recommendation._recommend(
                "recommend",
                {},
                self._pages(),
            )
        self.assertEqual(recommendations, [])
        self.assertEqual(opened, "")

    def test_new_stage_keeps_recommendations_outside_folder_skill(self):
        folder = {
            "success": True,
            "completed": True,
            "action": "folder_skill_awaiting_user_verification",
            "requires_user_verification": True,
            "skill_candidate_id": "candidate-id",
            "target_app": "FM26",
            "destination_name": "FM26 tactics",
        }
        recommendation = {
            "success": True,
            "completed": True,
            "cards": [{"title": "Tactic", "url": "https://tactic.test"}],
            "recommendation_count": 1,
            "tactic_page_opened": True,
        }
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="RECOMMEND_AND_OPEN_FOLDER",
        ), patch(
            "casper.skill_registry.match_pending_resume", return_value=None
        ), patch(
            "casper.skill_registry.match_verified", return_value=None
        ), patch(
            "casper.content_learning.execute", return_value=folder
        ) as learn, patch(
            "casper.content_recommendation.execute", return_value=recommendation
        ) as recommend:
            result = content_workflow.execute(
                "打开战术文件夹并推荐三个战术",
                "",
                content_authorized=True,
                skill_lookup_requested=True,
            )
        self.assertEqual(
            result["action"],
            "tactic_recommendations_awaiting_folder_verification",
        )
        learn.assert_called_once()
        self.assertEqual(
            learn.call_args.kwargs["requested_skill_scope"],
            "OPEN_DESTINATION_FOLDER",
        )
        recommend.assert_called_once()
        self.assertNotIn("cards", learn.call_args.kwargs)

    def test_verified_folder_skill_reopens_but_recommendations_run_again(self):
        skill = {
            "id": "skill-id",
            "status": "verified",
            "skill_scope": "OPEN_DESTINATION_FOLDER",
        }
        opened = {
            "success": True,
            "completed": True,
            "action": "opened_fm_tactic_folder",
        }
        recommendation = {
            "success": True,
            "completed": True,
            "cards": [],
            "recommendation_count": 0,
        }
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="RECOMMEND_AND_OPEN_FOLDER",
        ), patch(
            "casper.skill_registry.match_pending_resume", return_value=None
        ), patch(
            "casper.skill_registry.match_verified", return_value=skill
        ), patch(
            "casper.content_learning.reopen_verified_folder",
            return_value=opened,
        ) as reopen, patch(
            "casper.content_learning.execute"
        ) as learn, patch(
            "casper.content_recommendation.execute", return_value=recommendation
        ) as recommend:
            result = content_workflow.execute(
                "再打开战术文件夹并推荐三个战术",
                "",
                content_authorized=True,
                skill_lookup_requested=True,
            )
        self.assertEqual(result["action"], "opened_folder_and_recommended_tactics")
        reopen.assert_called_once_with(skill)
        learn.assert_not_called()
        recommend.assert_called_once()


if __name__ == "__main__":
    unittest.main()
