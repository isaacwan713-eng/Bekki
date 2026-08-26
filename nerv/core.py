"""NERV Core lifecycle facade used by the Bekki runtime."""

import threading

from .context_selector import ContextSelector
from .curiosity import CuriosityJournal
from .learning_engine import LearningEngine
from .knowledge_verification import CuriosityKnowledgeVerifier
from .profile_store import ProfileStore
from .profile_writer import ProfileWriter
from . import skill_management


class NervCore:
    def __init__(self, model_call, unload_model=None, base_dir=None):
        self.profile = ProfileStore(base_dir)
        self.context = ContextSelector(self.profile, base_dir)
        self.learning = LearningEngine(base_dir)
        self.curiosity = CuriosityJournal(model_call, unload_model, base_dir)
        self.knowledge_verification = CuriosityKnowledgeVerifier(
            model_call, unload_model
        )
        self.model_call = model_call
        self.unload_model = unload_model
        self._profile_write_lock = threading.Lock()
        self._profile_thread_lock = threading.Lock()
        self._profile_write_thread = None

    def context_for(self, audience, current_message=""):
        return self.context.prompt_context(audience, current_message)

    def learning_context_for(self, audience, current_message=""):
        return self.learning.context_for(audience, current_message)

    def accept_verified_skill(self, skill, user_feedback, session_id=""):
        return self.learning.accept_verified_casper_skill(
            skill,
            user_feedback,
            session_id=session_id,
        )

    def reject_skill_candidate(self, candidate_id, session_id=""):
        return self.learning.record_candidate_rejected(
            candidate_id,
            session_id=session_id,
        )

    def resolve_skill_forget(self, user_message):
        return skill_management.resolve_forget_request(
            user_message,
            self.learning.casper_verified_skills(),
            self.model_call,
            self.unload_model,
        )

    def classify_skill_forget_confirmation(self, user_message, pending_action):
        return skill_management.classify_forget_confirmation(
            user_message,
            pending_action,
            self.model_call,
            self.unload_model,
        )

    def forget_verified_skill(self, skill_id, confirmed=False):
        from casper import skill_registry

        removed = skill_registry.forget_verified(skill_id, confirmed=confirmed)
        if removed is not None:
            try:
                self.learning.reconcile_verified_casper_skills()
            except Exception as error:
                # Casper already completed the authoritative deletion. A
                # derived NERV-view failure must not misreport that operation.
                print("[NERV SKILL RECONCILE WARNING]", repr(error))
        return removed

    @staticmethod
    def skill_display_name(skill, language="zh-CN"):
        return skill_management.display_name(skill, language)

    def observe_completed_turn(
        self,
        user_message,
        response_mode,
        result_status="completed",
        action=None,
        verified=False,
        session_id="",
    ):
        """Best-effort post-result writes; never grants execution authority."""
        event = self.learning.record_result(
            user_message=user_message,
            response_mode=response_mode,
            result_status=result_status,
            action=action,
            verified=verified,
            session_id=session_id,
        )
        profile_results = []
        try:
            profile_results = ProfileWriter(self.profile, self.model_call).process(
                user_message
            )
        finally:
            if self.unload_model is not None:
                try:
                    self.unload_model("gemma3:4b")
                    print("[NERV PROFILE MODEL RELEASED] gemma3:4b")
                except Exception as error:
                    print("[NERV PROFILE MODEL RELEASE WARNING]", repr(error))
        return {"event": event, "profile_results": profile_results}

    def observe_completed_turn_async(
        self,
        user_message,
        response_mode,
        result_status="observed",
        action=None,
        verified=False,
        session_id="",
        assistant_reply="",
    ):
        """Persist the event now and write profile semantics off the reply path."""
        event = self.learning.record_result(
            user_message=user_message,
            response_mode=response_mode,
            result_status=result_status,
            action=action,
            verified=verified,
            session_id=session_id,
        )
        thread = threading.Thread(
            target=self._write_profile_safely,
            args=(
                str(user_message or ""),
                str(assistant_reply or ""),
                str(response_mode or ""),
            ),
            name="BekkiNervProfileWriter",
            daemon=True,
        )
        with self._profile_thread_lock:
            self._profile_write_thread = thread
        thread.start()
        return {"event": event, "profile_write": "scheduled"}

    def wait_for_pending_writes(self, timeout_seconds=45):
        """Wait for the previous turn's profile write before the next read."""
        with self._profile_thread_lock:
            thread = self._profile_write_thread
        if thread is None or not thread.is_alive():
            return True
        thread.join(max(0.0, float(timeout_seconds)))
        return not thread.is_alive()

    def _write_profile_safely(self, user_message, assistant_reply="", response_mode=""):
        # The runtime already accepts one user request at a time. This lock
        # prevents a very fast next turn from starting a second writer.
        with self._profile_write_lock:
            try:
                results = ProfileWriter(self.profile, self.model_call).process(
                    user_message
                )
                statuses = ",".join(
                    str(item.get("status") or "unknown")
                    for item in results
                    if isinstance(item, dict)
                ) or "none"
                print("[NERV PROFILE WRITTEN]", "statuses=" + statuses)
            except Exception as error:
                print("[NERV PROFILE WRITE WARNING]", repr(error))
            finally:
                if self.unload_model is not None:
                    try:
                        self.unload_model("gemma3:4b")
                        print("[NERV PROFILE MODEL RELEASED] gemma3:4b")
                    except Exception as error:
                        print("[NERV PROFILE MODEL RELEASE WARNING]", repr(error))
            try:
                result = self.curiosity.observe_turn(
                    user_message,
                    assistant_reply,
                    response_mode,
                )
                print(
                    "[NERV CURIOSITY OBSERVED]",
                    "status=" + str(result.get("status") or "unknown"),
                )
            except Exception as error:
                print("[NERV CURIOSITY WRITE WARNING]", repr(error))
