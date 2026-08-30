"""AI semantic profile proposals guarded by direct-user evidence."""

import json

from .schemas import PROFILE_WRITER_SCHEMA


class ProfileWriter:
    def __init__(self, store, model_call):
        self.store = store
        self.model_call = model_call

    def process(self, user_message):
        message = str(user_message or "").strip()
        if not message:
            return []
        packet = {
            "current_direct_user_message": message[:3000],
            "existing_profile": [
                {
                    "category": item.get("category"),
                    "key": item.get("key"),
                    "value": item.get("value"),
                }
                for item in self.store.active_items()[:80]
            ],
        }
        raw = self._call(packet)
        proposals = raw.get("proposals", []) if isinstance(raw, dict) else []
        if not isinstance(proposals, list):
            return []
        return [self.store.apply(item, message) for item in proposals[:3]]

    def _call(self, packet):
        return self.model_call(
            "prompts/nerv_profile_writer.txt",
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=4096,
            num_predict=700,
            think=False,
            model_name="gemma4:e4b",
            json_schema=PROFILE_WRITER_SCHEMA,
        )
