"""Verified-result learning journal and Casper Skills compatibility view."""

import hashlib
import json
import threading
from copy import deepcopy

from . import governance
from .schemas import LEARNING_STATES, SKILL_SCHEMA_VERSION


_LEARNING_LOCK = threading.RLock()
MAX_LEARNING_ITEMS = 100


class LearningEngine:
    def __init__(self, base_dir=None):
        self.directory = governance.data_directory(base_dir)
        self.events_path = self.directory / "learning_events.jsonl"
        self.skills_path = self.directory / "skills.json"
        if not self.skills_path.exists():
            governance.save_json(
                self.skills_path,
                {"schema_version": SKILL_SCHEMA_VERSION, "revision": 0, "items": []},
            )

    @staticmethod
    def _default_skills():
        return {
            "schema_version": SKILL_SCHEMA_VERSION,
            "revision": 0,
            "items": [],
        }

    def _load_skills(self):
        value = governance.load_json(self.skills_path, self._default_skills())
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            return self._default_skills()
        value.setdefault("schema_version", SKILL_SCHEMA_VERSION)
        value.setdefault("revision", 0)
        changed = False
        for index, item in enumerate(value["items"]):
            repaired = self._repair_local_summary(item)
            if repaired != item:
                value["items"][index] = repaired
                changed = True
        if changed:
            value["revision"] = int(value.get("revision", 0)) + 1
            governance.save_json(self.skills_path, value)
        return value

    @classmethod
    def _repair_local_summary(cls, item):
        """Migrate stale NERV wording from authoritative bounded fields."""
        if not isinstance(item, dict):
            return item
        if (
            cls._safe_text(item.get("state"), 40) != "VERIFIED"
            or cls._safe_text(item.get("skill_scope"), 80)
            != "OPEN_DESTINATION_FOLDER"
        ):
            return item
        repaired = dict(item)
        content_kind = cls._safe_text(item.get("content_kind"), 100)
        repaired["intent_summary"] = (
            "Locate and open the reusable "
            + (content_kind or "content")
            + " destination folder"
        )[:300]
        repaired["parameters"] = []
        return repaired

    def record_result(
        self,
        user_message,
        response_mode,
        result_status,
        action=None,
        verified=False,
        session_id="",
    ):
        # Generic runtime observation cannot mint verification authority.
        # VERIFIED is emitted only by accept_verified_casper_skill after both
        # Casper's machine receipt and explicit user acceptance are present.
        state = "TESTED" if result_status == "tested" else "OBSERVED"
        if state not in LEARNING_STATES:
            state = "OBSERVED"
        event = {
            "event": "request_result",
            "state": state,
            # The learning journal needs correlation, not a second copy of the
            # user's possibly private message.
            "request_digest": hashlib.sha256(
                str(user_message or "").encode("utf-8")
            ).hexdigest(),
            "response_mode": governance.compact_text(response_mode, 60),
            "result_status": governance.compact_text(result_status, 60),
            "action": governance.compact_text(action, 120),
            "session_id": governance.compact_text(session_id, 160),
            "provenance": "bekki_runtime",
        }
        if verified:
            event["verification_claim"] = "ignored_without_casper_receipt"
        governance.append_jsonl(self.events_path, event)
        return event

    @staticmethod
    def _digest(value):
        return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()

    @staticmethod
    def _safe_text(value, maximum):
        return governance.compact_text(value, maximum)

    @classmethod
    def _summary_from_verified_skill(cls, skill):
        """Return a path-free NERV record from one Casper-verified skill."""
        if not isinstance(skill, dict):
            return None
        skill_id = cls._safe_text(skill.get("id"), 120)
        required = {
            "capability": cls._safe_text(skill.get("capability"), 120),
            "skill_scope": cls._safe_text(skill.get("skill_scope"), 80),
            "target_app": cls._safe_text(skill.get("target_app"), 160),
            "content_kind": cls._safe_text(skill.get("content_kind"), 100),
            "local_adapter": cls._safe_text(skill.get("local_adapter"), 80),
        }
        if not skill_id.startswith("skill_") or any(not value for value in required.values()):
            return None
        applicability = skill.get("applicability")
        if not isinstance(applicability, dict):
            applicability = {}
        parameters = skill.get("parameters")
        if not isinstance(parameters, list):
            parameters = []
        intent_summary = cls._safe_text(skill.get("intent_summary"), 300)
        if required["skill_scope"] == "OPEN_DESTINATION_FOLDER":
            # Older verified Casper records may contain tutorial-adjacent copy
            # or install wording even though their authoritative scope and
            # machine receipt prove only an opened destination. Reconcile the
            # descriptive NERV view to that narrower verified capability.
            intent_summary = (
                "Locate and open the reusable "
                + required["content_kind"]
                + " destination folder"
            )[:300]
            parameters = []
        return {
            "id": skill_id,
            "state": "VERIFIED",
            **required,
            "intent_summary": intent_summary,
            "parameters": [
                cls._safe_text(value, 100)
                for value in parameters[:12]
                if cls._safe_text(value, 100)
            ],
            "applicability": {
                "platform": cls._safe_text(applicability.get("platform"), 40),
                "version_constraints": [
                    cls._safe_text(value, 120)
                    for value in applicability.get("version_constraints", [])[:8]
                    if cls._safe_text(value, 120)
                ] if isinstance(applicability.get("version_constraints"), list) else [],
            },
            "source": "casper_verified_skill",
        }

    def _upsert_verified_summary(self, summary, increment_confirmation=False):
        if not isinstance(summary, dict):
            return None
        now = governance.now_iso()
        with _LEARNING_LOCK:
            state = self._load_skills()
            existing = next(
                (
                    item for item in state["items"]
                    if isinstance(item, dict) and item.get("id") == summary.get("id")
                ),
                None,
            )
            if (
                existing is not None
                and not increment_confirmation
                and all(existing.get(key) == value for key, value in summary.items())
            ):
                return deepcopy(existing)
            record = dict(summary)
            record["first_verified_at"] = (
                existing.get("first_verified_at", now) if existing else now
            )
            record["last_verified_at"] = now
            previous_count = 0
            if existing:
                try:
                    previous_count = max(0, int(existing.get("confirmation_count", 0)))
                except (TypeError, ValueError):
                    previous_count = 0
            record["confirmation_count"] = max(
                1,
                previous_count + (1 if increment_confirmation else 0),
            )
            if existing is None:
                state["items"].append(record)
            else:
                state["items"][state["items"].index(existing)] = record
            state["items"] = state["items"][-MAX_LEARNING_ITEMS:]
            state["revision"] = int(state.get("revision", 0)) + 1
            governance.save_json(self.skills_path, state)
        return deepcopy(record)

    def accept_verified_casper_skill(
        self,
        skill,
        user_feedback,
        session_id="",
    ):
        """Import only a machine-complete skill with explicit user acceptance."""
        feedback = str(user_feedback or "").strip()
        machine = skill.get("machine_verification") if isinstance(skill, dict) else None
        valid_receipt = (
            isinstance(skill, dict)
            and skill.get("status") == "verified"
            and skill.get("user_verified") is True
            and bool(feedback)
            and isinstance(machine, dict)
            and machine.get("success") is True
            and machine.get("completed") is True
        )
        summary = self._summary_from_verified_skill(skill) if valid_receipt else None
        if summary is None:
            governance.append_jsonl(
                self.events_path,
                {
                    "event": "verified_skill_import_rejected",
                    "state": "OBSERVED",
                    "skill_id_digest": self._digest(
                        skill.get("id") if isinstance(skill, dict) else ""
                    ),
                    "reason": "missing_machine_or_user_verification",
                },
            )
            return None
        record = self._upsert_verified_summary(summary, increment_confirmation=True)
        governance.append_jsonl(
            self.events_path,
            {
                "event": "skill_learning_state_changed",
                "state": "VERIFIED",
                "skill_id": record.get("id"),
                "capability": record.get("capability"),
                "target_app": record.get("target_app"),
                "feedback_digest": self._digest(feedback),
                "session_id": self._safe_text(session_id, 160),
                "provenance": "casper_machine_and_user_verified",
            },
        )
        return record

    def record_candidate_rejected(self, candidate_id, session_id=""):
        """Record rejection without promoting or retaining candidate content."""
        event = {
            "event": "skill_candidate_feedback",
            "state": "DEPRECATED",
            "candidate_id_digest": self._digest(candidate_id),
            "session_id": self._safe_text(session_id, 160),
            "provenance": "explicit_user_rejection",
        }
        governance.append_jsonl(self.events_path, event)
        return event

    def reconcile_verified_casper_skills(self):
        """Rebuild the sanitized NERV view from Casper's authoritative registry."""
        available, skills = self._casper_verified_snapshot()
        if not available:
            return []
        imported = []
        verified_ids = set()
        for skill in skills[:MAX_LEARNING_ITEMS]:
            summary = self._summary_from_verified_skill(skill)
            if summary is not None:
                verified_ids.add(summary["id"])
                record = self._upsert_verified_summary(summary)
                if record is not None:
                    imported.append(record)
        with _LEARNING_LOCK:
            state = self._load_skills()
            changed = False
            for item in state.get("items", []):
                if (
                    isinstance(item, dict)
                    and item.get("source") == "casper_verified_skill"
                    and item.get("state") == "VERIFIED"
                    and item.get("id") not in verified_ids
                ):
                    item["state"] = "DEPRECATED"
                    item["deprecated_at"] = governance.now_iso()
                    changed = True
            if changed:
                state["revision"] = int(state.get("revision", 0)) + 1
                governance.save_json(self.skills_path, state)
        return imported

    def verified_items(self):
        self.reconcile_verified_casper_skills()
        return [
            deepcopy(item)
            for item in self._load_skills().get("items", [])
            if isinstance(item, dict) and item.get("state") == "VERIFIED"
        ]

    def context_for(self, audience, current_message=""):
        del current_message
        audience = str(audience or "").lower().strip()
        if audience != "melchior":
            return ""
        items = self.verified_items()
        items.sort(
            key=lambda item: str(item.get("last_verified_at") or ""),
            reverse=True,
        )
        summaries = [
            {
                "capability": item.get("capability"),
                "skill_scope": item.get("skill_scope"),
                "target_app": item.get("target_app"),
                "content_kind": item.get("content_kind"),
                "intent_summary": item.get("intent_summary"),
                "parameters": item.get("parameters", []),
                "confirmation_count": item.get("confirmation_count", 1),
            }
            for item in items[:8]
        ]
        return json.dumps(summaries, ensure_ascii=False, separators=(",", ":"))

    def inventory_reply(self, language="zh-CN"):
        """Render the verified inventory without allowing a writer to expand it."""
        items = self.verified_items()
        items.sort(
            key=lambda item: str(item.get("last_verified_at") or ""),
            reverse=True,
        )
        language = str(language or "zh-CN")
        empty = {
            "zh-CN": "目前还没有学习任何经过你确认的可复用操作。",
            "en": "I have not learned any reusable operations that you verified yet.",
            "es": "Aún no he aprendido ninguna operación reutilizable verificada por ti.",
            "ja": "あなたが確認した再利用可能な操作は、まだ学習していません。",
        }
        if not items:
            return empty.get(language, empty["zh-CN"]), 0

        kind_names = {
            "zh-CN": {"tactics": "战术", "tactic": "战术"},
            "en": {},
            "es": {"tactics": "tácticas", "tactic": "tácticas"},
            "ja": {"tactics": "戦術", "tactic": "戦術"},
        }
        operations = []
        for item in items[:8]:
            target = self._safe_text(item.get("target_app"), 160)
            kind = self._safe_text(item.get("content_kind"), 100)
            shown_kind = kind_names.get(language, {}).get(kind.casefold(), kind)
            scope = self._safe_text(item.get("skill_scope"), 80)
            if scope == "OPEN_DESTINATION_FOLDER":
                if language == "en":
                    operation = "Open the " + shown_kind + " folder for " + target
                elif language == "es":
                    operation = "Abrir la carpeta de " + shown_kind + " de " + target
                elif language == "ja":
                    operation = target + " の" + shown_kind + "フォルダーを開く"
                else:
                    operation = "打开 " + target + " 的" + shown_kind + "文件夹"
            else:
                operation = self._safe_text(item.get("intent_summary"), 300)
            if operation:
                operations.append(operation)

        if not operations:
            return empty.get(language, empty["zh-CN"]), 0
        prefixes = {
            "zh-CN": "目前，我学会了以下经过你确认的操作：",
            "en": "I have learned these operations that you verified:",
            "es": "He aprendido estas operaciones que verificaste:",
            "ja": "現在、あなたが確認した次の操作を学習しています：",
        }
        lines = [prefixes.get(language, prefixes["zh-CN"])]
        lines.extend(
            str(index) + ". " + operation
            for index, operation in enumerate(operations, start=1)
        )
        return "\n".join(lines), len(operations)

    @staticmethod
    def _casper_verified_snapshot():
        """Return availability plus Casper's authoritative verified summaries."""
        try:
            from casper import skill_registry

            summaries = skill_registry._skill_summaries()
        except Exception as error:
            print("[NERV SKILL ADAPTER WARNING]", repr(error))
            return False, []
        return True, summaries if isinstance(summaries, list) else []

    @staticmethod
    def casper_verified_skills():
        """Read-only compatibility view; Casper retains lifecycle authority."""
        _available, summaries = LearningEngine._casper_verified_snapshot()
        return summaries
