# Bekki NERV Learning V1

Build ID: `bekki-nerv-learning-v1-3-20260825`

V1.3 adds a dedicated `NERV_SKILL_ACTION` lifecycle for forgetting a verified
reusable skill. A reliable model resolves only an exact ID from Casper's
bounded verified catalog, then Bekki displays the matched operation and waits
for a separate explicit confirmation turn. Casper refuses deletion unless the
caller passes literal `confirmed=True`; cancellation, ambiguity, invented IDs,
and unrelated new requests cannot delete a skill. After confirmed deletion,
NERV deprecates its derived mirror and the forgotten skill is removed from both
the primary Casper registry and its recovery backup. Reminder deletion remains
on the separate `TASK_ACTION` path.

V1.2.6 audits the compact model's contradictory local/skill signal with
`gemma3:12b`. The focused model returns only `NERV_LEARNING` or `OTHER` and is
released immediately. This ensures verified-skill inventory requests reach the
V1.2.5 deterministic renderer without moving ordinary semantic routing into
Python or disturbing bounded device actions.

V1.2.5 introduces an AI-selected `NERV_LEARNING` context profile for questions
that list verified learned operations. NERV then renders the inventory directly
from its bounded structured records instead of asking the final writing model
to paraphrase them. This prevents stale memory from changing an open-folder
skill into a copy/install claim while keeping semantic routing AI-owned.

V1.2.4 repairs legacy wording already stored in `data/nerv/skills.json`.
Verified `OPEN_DESTINATION_FOLDER` records are migrated from their authoritative
scope and content type during local loading, then saved back with no parameters.
This works even when the Casper compatibility adapter is temporarily
unavailable and does not require deleting or relearning the skill.

V1.2.3 places the current verified-learning JSON after Recent Conversation in
the final writer prompt and marks it as the authoritative view. It overrides
older assistant wording about learned skills, preventing stale conversation
history from reintroducing a copy/install description after V1.2.2 repaired
the stored scope. No relearning is required.

V1.2.2 makes the verified `skill_scope` authoritative when learning context is
described. For `OPEN_DESTINATION_FOLDER`, tutorial-adjacent copy/install text
cannot replace the grounded plan's open-folder intent. The NERV compatibility
view also repairs older verified records at read time, so users do not need to
delete or relearn an already working skill.

V1.2.1 fixes the user-verification turn after a learned folder is opened. The
reliable model now owns both the checkpoint-relation decision and the final
ACCEPT/REJECT judgment. A bare “对了” is grounded as acceptance only for the
active opened-folder verification checkpoint; “对了，……” with a genuinely new
following request remains eligible for NEW_REQUEST/UNRELATED.

V1.2 adds the first-learning route into Casper's existing verified content
workflow. Explicit requests to learn and immediately open an application's
reusable game-content destination receive a focused `gemma3:12b` audit when
the detailed router mislabels them as a normal application action. The audit
can select `CONTENT_DEVICE_ACTION`; Python only validates the closed enum and
does not classify the user's words. File, system, and library actions cannot
enter this bootstrap audit.

V1.1 always supplies an explicit verified-learning array to the final writer,
including `[]` when no skill exists. In that empty case, built-in capabilities,
model assignments, general knowledge, and ordinary observations cannot be
reported as learned operations.

NERV Learning V1 adds a governed learning view above Casper's existing skill
registry. Casper remains the only execution and verified-skill authority.
NERV cannot turn a chat response, search result, model claim, or merely
successful process return into a reusable skill.

## Verified learning gate

A reusable learning record is created only after all of these are present:

1. Casper created a bounded temporary candidate.
2. Casper recorded a completed machine-verification receipt.
3. The user explicitly confirmed that the result was correct.
4. Casper committed the candidate as a verified Skill.

NERV then stores only a sanitized summary: capability, scope, target app,
content type, adapter, bounded parameters, applicability, timestamps, and a
confirmation count. Local paths, source URLs, raw requests, raw feedback, and
session identifiers are not copied into `data/nerv/skills.json`.

## Lifecycle

- Ordinary completed requests remain `OBSERVED` learning events.
- User-rejected candidates produce a digest-only `DEPRECATED` event and never
  enter the learned-skill view.
- Reconfirming the same verified Casper skill updates one NERV record.
- If Casper's authoritative registry no longer contains a mirrored skill,
  NERV marks its local view `DEPRECATED`.
- If the Casper adapter is temporarily unavailable, NERV preserves the last
  valid view instead of falsely deprecating it.

## Context and authority

The final local writer may receive up to eight sanitized verified-learning
summaries so Bekki can answer questions such as “你学会了哪些操作？”. MAGI and
external AI receive none. The summary is descriptive only; executing a learned
operation still routes through MAGI, Melchior, and Casper normally.

## Validation

- 10 focused Learning V1 tests cover receipt gating, sanitization,
  deduplication, rejection, audience isolation, deprecation, adapter failure,
  and runtime wiring.
- Existing NERV Core Profile tests remain enabled.
- Full suite: 624 tests passed; 4 platform-dependent tests skipped.
- The Stable V1.3.9.5 UI source files are unchanged.
