"""Least-privilege NERV context packets for Bekki controllers."""

import json

from . import governance


AUDIENCE_LIMITS = {
    "magi": 4,
    "melchior": 8,
    "balthasar": 6,
    "casper": 5,
    "external_ai": 0,
}

AUDIENCE_CATEGORIES = {
    "magi": {"location", "device", "constraint"},
    "melchior": {"location", "device", "preference", "routine", "constraint"},
    "balthasar": {"preference", "routine", "relationship"},
    "casper": {"location", "device", "constraint"},
    "external_ai": set(),
}


class ContextSelector:
    def __init__(self, profile_store, base_dir=None):
        self.profile_store = profile_store
        self.base_dir = base_dir

    def select(self, audience, current_message=""):
        audience = str(audience or "").lower().strip()
        maximum = AUDIENCE_LIMITS.get(audience, 0)
        allowed = AUDIENCE_CATEGORIES.get(audience, set())
        if maximum <= 0:
            return []
        items = [
            item for item in self.profile_store.active_items()
            if item.get("category") in allowed
            and item.get("sensitivity") == "NORMAL"
        ]
        # Recency is a deterministic budget policy. Semantic interpretation
        # remains with the receiving AI controller.
        items.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return [
            {
                "category": item.get("category"),
                "key": item.get("key"),
                "value": item.get("value"),
                "confidence": item.get("confidence"),
            }
            for item in items[:maximum]
        ]

    def prompt_context(self, audience, current_message=""):
        selected = self.select(audience, current_message)
        if not selected:
            return ""
        return json.dumps(selected, ensure_ascii=False, separators=(",", ":"))
