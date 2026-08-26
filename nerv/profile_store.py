"""Versioned structured profile store with review and conflict history."""

import hashlib
from copy import deepcopy

from . import governance
from .schemas import PROFILE_CATEGORIES, PROFILE_SCHEMA_VERSION


class ProfileStore:
    def __init__(self, base_dir=None):
        self.directory = governance.data_directory(base_dir)
        self.path = self.directory / "profile.json"
        self.audit_path = self.directory / "audit.jsonl"
        self._ensure()

    @staticmethod
    def _default():
        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "revision": 0,
            "items": [],
        }

    def _ensure(self):
        if not self.path.exists():
            governance.save_json(self.path, self._default())

    def load(self):
        value = governance.load_json(self.path, self._default())
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            return self._default()
        value.setdefault("schema_version", PROFILE_SCHEMA_VERSION)
        value.setdefault("revision", 0)
        return value

    def active_items(self):
        return [
            deepcopy(item)
            for item in self.load().get("items", [])
            if isinstance(item, dict) and item.get("status") == "active"
        ]

    @staticmethod
    def _item_id(category, key):
        material = (str(category) + "\0" + str(key)).encode("utf-8")
        return hashlib.sha256(material).hexdigest()[:20]

    def apply(self, proposal, direct_user_message):
        """Apply one validated AI proposal; Python owns only policy/state."""
        operation = str(proposal.get("operation") or "NONE").upper()
        if operation == "NONE":
            return {"status": "ignored", "reason": "no_change"}
        category = str(proposal.get("category") or "").lower().strip()
        key = governance.compact_text(proposal.get("key"), 100).lower()
        value = governance.compact_text(proposal.get("value"), 500)
        quote = governance.compact_text(proposal.get("evidence_quote"), 500)
        sensitivity = str(proposal.get("sensitivity") or "SENSITIVE").upper()
        try:
            confidence = float(proposal.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.0
        if (
            category not in PROFILE_CATEGORIES
            or not key
            or operation not in {"ADD", "UPDATE", "REMOVE"}
            or not governance.quote_is_grounded(quote, direct_user_message)
            or not 0 <= confidence <= 1
        ):
            self._audit(
                "profile_proposal_rejected",
                self._proposal_metadata(proposal),
                "invalid_or_ungrounded",
            )
            return {"status": "rejected", "reason": "invalid_or_ungrounded"}
        if operation != "REMOVE" and not value:
            self._audit(
                "profile_proposal_rejected",
                self._proposal_metadata(proposal),
                "missing_value",
            )
            return {"status": "rejected", "reason": "missing_value"}

        state = self.load()
        item_id = self._item_id(category, key)
        existing = next(
            (item for item in state["items"] if item.get("id") == item_id), None
        )
        now = governance.now_iso()
        if operation == "UPDATE" and (
            existing is None or existing.get("status") == "removed"
        ):
            self._audit(
                "profile_operation_reconciled",
                self._proposal_metadata(proposal),
                "missing_update_target_became_add",
            )
            # The model owns the semantic decision and proposed value. The
            # store owns lifecycle state: an UPDATE without a live target is
            # necessarily the first ADD for that stable key.
            operation = "ADD"
        if operation == "REMOVE":
            if existing is None:
                return {"status": "ignored", "reason": "not_found"}
            existing["status"] = "removed"
            existing["updated_at"] = now
            existing["removal_evidence_quote"] = quote
            result_status = "removed"
        else:
            add_conflict = (
                operation == "ADD"
                and existing is not None
                and existing.get("status") == "active"
                and governance.compact_text(existing.get("value"), 500) != value
            )
            if (
                operation == "ADD"
                and existing is not None
                and existing.get("status") == "active"
                and governance.compact_text(existing.get("value"), 500) == value
            ):
                return {"status": "ignored", "reason": "duplicate"}
            review_status = (
                "pending_review"
                if sensitivity == "SENSITIVE" or confidence < 0.80 or add_conflict
                else "active"
            )
            record = {
                "id": item_id,
                "category": category,
                "key": key,
                "value": value,
                "confidence": confidence,
                "source_kind": "user_explicit",
                "evidence_quote": quote,
                "sensitivity": sensitivity,
                "status": review_status,
                "created_at": existing.get("created_at", now) if existing else now,
                "updated_at": now,
                "version": int(existing.get("version", 0)) + 1 if existing else 1,
            }
            if review_status == "pending_review":
                # A proposal awaiting review must not silently replace an
                # already active fact. It is stored as a separate candidate.
                record["id"] = (
                    item_id + "-pending-"
                    + hashlib.sha256(now.encode("utf-8")).hexdigest()[:8]
                )
                record["target_id"] = item_id if existing else None
                state["items"].append(record)
            elif existing is None:
                state["items"].append(record)
            else:
                history = list(existing.get("history", []))[-9:]
                history.append(
                    {
                        "value": existing.get("value"),
                        "status": existing.get("status"),
                        "updated_at": existing.get("updated_at"),
                    }
                )
                record["history"] = history
                state["items"][state["items"].index(existing)] = record
            result_status = review_status
        state["revision"] = int(state.get("revision", 0)) + 1
        governance.save_json(self.path, state)
        self._audit(
            "profile_changed",
            {"id": item_id, "operation": operation, "status": result_status},
        )
        return {"status": result_status, "id": item_id}

    def _audit(self, event, payload, reason=None):
        record = {"event": event, "payload": payload}
        if reason:
            record["reason"] = reason
        governance.append_jsonl(self.audit_path, record)

    @staticmethod
    def _proposal_metadata(proposal):
        return {
            "operation": str(proposal.get("operation") or "")[:20],
            "category": str(proposal.get("category") or "")[:40],
            "key": governance.compact_text(proposal.get("key"), 100),
        }
