"""Generic AI-led acquisition workflow for game content and add-ons."""


MAX_ISOLATED_CONTEXT_CHARS = 1200


def _classify_context_scope(message, recent_context):
    """Let AI decide whether this turn needs any prior conversation."""
    import tools

    payload = (
        "CURRENT_REQUEST (authoritative):\n"
        + str(message)[:900]
        + "\nRECENT_CONTEXT (reference resolution only):\n"
        + str(recent_context)[-MAX_ISOLATED_CONTEXT_CHARS:]
    )
    attempts = (
        (
            "prompts/casper_content_context_scope.txt",
            "gemma3:12b",
            700,
            4096,
        ),
        (
            "prompts/casper_content_context_scope_retry.txt",
            "gemma3:12b",
            1400,
            8192,
        ),
    )
    for prompt_path, model_name, output_budget, context_budget in attempts:
        raw = tools.run_ai_prompt(
            prompt_path,
            payload,
            expect_json=False,
            num_ctx=context_budget,
            num_predict=output_budget,
            think=False,
            model_name=model_name,
        )
        value = str(raw or "").strip()
        if value in {"CURRENT_ONLY", "NEEDS_CONTEXT"}:
            return value
        payload += "\nINVALID_PREVIOUS_OUTPUT:\n" + value[:80]
    return ""


def _isolated_recent_context(scope, recent_context):
    """Apply an AI-authored context boundary without semantic Python rules."""
    if scope == "CURRENT_ONLY":
        return ""
    if scope == "NEEDS_CONTEXT":
        return str(recent_context)[-MAX_ISOLATED_CONTEXT_CHARS:]
    return None


def _context_scope_failure():
    return {
        "success": False,
        "completed": False,
        "needs_clarification": True,
        "clarification": "我还不能可靠地判断这条请求是否引用了之前的内容，请把完整请求再说一次。",
        "reason": "Content context-scope AI returned invalid output twice.",
    }


def _scope_mismatch(required_scope):
    return {
        "success": False,
        "completed": False,
        "needs_clarification": True,
        "clarification": "之前保存的方法与当前操作阶段不一致，需要重新学习。",
        "reason": "Explicit resume skill did not have required scope " + required_scope + ".",
    }


def _preserve_pending_retry(result, skill):
    """Keep a learned candidate resumable after a retryable acquisition miss."""
    if not isinstance(result, dict) or not isinstance(skill, dict):
        return result
    if not (
        result.get("needs_clarification")
        and str(skill.get("status") or "").startswith("pending")
        and str(skill.get("id") or "").strip()
    ):
        return result
    return {
        **result,
        "content_installation_retry_available": True,
        "resume_skill_id": str(skill.get("id") or "").strip(),
        "target_app": str(skill.get("target_app") or "").strip(),
        "destination_name": str(skill.get("destination_name") or "").strip(),
        "original_request": str(skill.get("original_request") or "").strip(),
    }


def _preserve_exact_resume_retry(result, resume_skill_id, original_request):
    """Keep an exact checkpoint reachable before its candidate is loaded.

    The candidate ID comes from the active checkpoint, not from model output.
    This helper adds only structural transition metadata; it does not inspect
    the request's meaning or open the pending-candidate catalog.
    """
    if not isinstance(result, dict) or not result.get("needs_clarification"):
        return result
    candidate_id = str(resume_skill_id or "").strip()
    request = str(original_request or "").strip()[:900]
    if not candidate_id or not request:
        return result
    return {
        **result,
        "content_installation_retry_available": True,
        "resume_skill_id": candidate_id,
        "original_request": request,
    }


def _terminal_exact_resume(result, resume_skill_id):
    """Mark a structurally impossible exact resume as terminal."""
    return {
        **result,
        "exact_resume_terminal": True,
        "resume_skill_id": str(resume_skill_id or "").strip(),
    }


def _classify_stage(message, recent_context):
    import tools

    prompt_input = (
        "RECENT_CONTEXT:\n" + str(recent_context)[-600:]
        + "\nCURRENT_REQUEST:\n" + str(message)[:700]
    )
    attempts = (
        (
            "prompts/casper_content_stage.txt",
            "llama3.2:latest",
            260,
            2048,
        ),
        (
            "prompts/casper_content_stage_retry.txt",
            "gemma3:12b",
            900,
            4096,
        ),
    )
    for prompt_path, model_name, output_budget, context_budget in attempts:
        raw = tools.run_ai_prompt(
            prompt_path,
            prompt_input,
            expect_json=False,
            num_ctx=context_budget,
            num_predict=output_budget,
            think=False,
            model_name=model_name,
        )
        value = str(raw or "").strip().upper()
        if value in {
            "RESEARCH_AND_INSTALL",
            "RECOMMEND_AND_OPEN_FOLDER",
            "OPEN_FOLDER_ONLY",
            "INSTALL_LOCAL_CONTENT",
            "OTHER",
        }:
            return value
        prompt_input += "\nINVALID_PREVIOUS_OUTPUT:\n" + value[:80]
    return ""


def _classify_authorized_stage(message, recent_context):
    """Choose only the stage after upstream AI already owns the workflow."""
    import tools

    prompt_input = (
        "RECENT_CONTEXT:\n" + str(recent_context)[-600:]
        + "\nCURRENT_REQUEST:\n" + str(message)[:700]
    )
    attempts = (
        (
            "prompts/casper_content_authorized_stage.txt",
            "llama3.2:latest",
            260,
            2048,
        ),
        (
            "prompts/casper_content_authorized_stage_retry.txt",
            "gemma3:12b",
            900,
            4096,
        ),
    )
    for prompt_path, model_name, output_budget, context_budget in attempts:
        raw = tools.run_ai_prompt(
            prompt_path,
            prompt_input,
            expect_json=False,
            num_ctx=context_budget,
            num_predict=output_budget,
            think=False,
            model_name=model_name,
        )
        value = str(raw or "").strip().upper()
        if value in {
            "RESEARCH_AND_INSTALL",
            "RECOMMEND_AND_OPEN_FOLDER",
            "OPEN_FOLDER_ONLY",
            "INSTALL_LOCAL_CONTENT",
        }:
            return value
        prompt_input += "\nINVALID_PREVIOUS_OUTPUT:\n" + value[:80]
    return ""


def execute(
    message,
    recent_context,
    status_callback=None,
    content_authorized=False,
    resume_skill_id=None,
    skill_lookup_requested=False,
):
    context_scope = _classify_context_scope(message, recent_context)
    isolated_context = _isolated_recent_context(
        context_scope, recent_context
    )
    if isolated_context is None:
        failure = _context_scope_failure()
        if resume_skill_id:
            return _preserve_exact_resume_retry(
                failure, resume_skill_id, message
            )
        return failure

    # Current-stage meaning is settled before any pending or verified Skills
    # data becomes visible. Python validates only the AI-authored enum and then
    # enforces the declared stage's capability boundary.
    stage = (
        _classify_authorized_stage(message, isolated_context)
        if content_authorized
        else _classify_stage(message, isolated_context)
    )
    if stage == "":
        failure = {
            "success": False,
            "needs_clarification": True,
            "clarification": "你是想先上网寻找内容，还是安装已经下载好的游戏内容？",
            "reason": "Content-stage AI returned invalid output twice.",
        }
        if resume_skill_id:
            return _preserve_exact_resume_retry(
                failure, resume_skill_id, message
            )
        return failure

    # A pending candidate is reachable only through one exact ID restored from
    # an active checkpoint by the upstream controller. Ordinary skill lookup
    # never opens the pending-candidate store.
    if resume_skill_id:
        from . import content_research
        from . import skill_registry

        skill = (
            skill_registry.load_pending(resume_skill_id)
            or skill_registry.load_verified(resume_skill_id)
        )
        if not skill:
            return _terminal_exact_resume({
                "success": False,
                "completed": False,
                "needs_clarification": True,
                "clarification": "之前的临时技能或已验证技能已经不存在，需要重新学习。",
                "reason": "The requested pending or verified skill was unavailable.",
            }, resume_skill_id)
        if stage != "RESEARCH_AND_INSTALL":
            return _preserve_pending_retry(
                _scope_mismatch("INSTALL_CONTENT"), skill
            )
        if skill.get("skill_scope") != "INSTALL_CONTENT":
            return _terminal_exact_resume(
                _scope_mismatch("INSTALL_CONTENT"), resume_skill_id
            )
        result = content_research.execute(
            message,
            isolated_context,
            status_callback=status_callback,
            procedure=skill,
        )
        return _preserve_pending_retry(result, skill)

    if stage == "OPEN_FOLDER_ONLY":
        from . import content_learning
        from . import skill_registry

        if skill_lookup_requested:
            skill = skill_registry.match_verified(message, isolated_context)
            if (
                isinstance(skill, dict)
                and skill.get("skill_scope") == "OPEN_DESTINATION_FOLDER"
            ):
                return content_learning.reopen_verified_folder(skill)
        return content_learning.execute(
            message,
            isolated_context,
            status_callback=status_callback,
            requested_skill_scope="OPEN_DESTINATION_FOLDER",
        )
    if stage == "RECOMMEND_AND_OPEN_FOLDER":
        from . import content_learning
        from . import content_recommendation
        from . import skill_registry

        folder_result = None
        if skill_lookup_requested:
            skill = skill_registry.match_verified(message, isolated_context)
            if (
                isinstance(skill, dict)
                and skill.get("skill_scope") == "OPEN_DESTINATION_FOLDER"
            ):
                folder_result = content_learning.reopen_verified_folder(skill)
        if folder_result is None:
            folder_result = content_learning.execute(
                message,
                isolated_context,
                status_callback=status_callback,
                requested_skill_scope="OPEN_DESTINATION_FOLDER",
            )
        if not folder_result.get("success"):
            return folder_result
        recommendation = content_recommendation.execute(
            message,
            isolated_context,
            status_callback=status_callback,
        )
        combined = {
            **folder_result,
            "cards": recommendation.get("cards", []),
            "recommendation_count": recommendation.get(
                "recommendation_count", 0
            ),
            "tactic_page_opened": recommendation.get(
                "tactic_page_opened", False
            ),
            "opened_url": recommendation.get("opened_url", ""),
            "recommendation_issue": (
                "" if recommendation.get("success")
                else recommendation.get("reason", "")
            ),
        }
        if folder_result.get("requires_user_verification"):
            combined["action"] = (
                "tactic_recommendations_awaiting_folder_verification"
            )
        else:
            combined["action"] = "opened_folder_and_recommended_tactics"
        return combined
    if stage == "RESEARCH_AND_INSTALL":
        if skill_lookup_requested:
            from . import content_research
            from . import skill_registry

            skill = skill_registry.match_verified(message, isolated_context)
            if (
                isinstance(skill, dict)
                and skill.get("skill_scope") == "INSTALL_CONTENT"
            ):
                return content_research.execute(
                    message,
                    isolated_context,
                    status_callback=status_callback,
                    procedure=skill,
                )
        from . import content_learning

        return content_learning.execute(
            message,
            isolated_context,
            status_callback=status_callback,
            requested_skill_scope="INSTALL_CONTENT",
        )
    if stage == "INSTALL_LOCAL_CONTENT":
        # A bounded first adapter does not own the generic workflow semantics.
        from . import game_content

        return game_content.execute(message, isolated_context)
    return {
        "success": False,
        "needs_clarification": False,
        "unsupported": True,
        "reason": "The request is not a supported game-content workflow.",
    }
