# Balthasar Companion + Social JSON Hotfix V1.10.47.8

Build ID: `bekki-balthasar-companion-social-json-hotfix-v1-10-47-8-20260902`

## Companion delivery

- Companion Watch still owns the current video frame and every factual claim
  about it. Balthasar now supplies only mood, tone, support style, familiarity,
  cadence and conversational move before the vision reply is written.
- Automatic reactions use a deterministic Balthasar state/turn rotation, so
  they gain variety without another model call. A direct user message receives
  one compact Balthasar plan from the same model used for its visual answer,
  avoiding a model swap on the 16 GB runtime.
- Recent Bekki lines are checked for exact spoken-form repetition. Empty,
  duplicate and stock caption-like reactions stay silent rather than filling
  the panel with generic comments.
- Only a direct user-authored companion message may apply Balthasar's bounded
  emotional deltas. Automatic frame reactions never drift persistent emotion.

## Social extraction recovery

- Social evidence schema strings and warnings now have explicit length/count
  limits to prevent a malformed title from consuming the entire output budget.
- If a later social item is cut off, Python keeps every fully closed object
  before it and records a partial-recovery warning. No text, author, time or
  engagement value is repaired or invented.
- A Bilibili page that produced valid DOM candidates and several complete
  extracted rows therefore continues into title resolution, post opening and
  card building instead of collapsing to zero evidence.

## Expected diagnostics

- `[BALTHASAR COMPANION PLAN] ... source=state_rotation` for automatic looks.
- `[BALTHASAR COMPANION PLAN] ... source=ai` for a valid direct-message plan.
- `[SOCIAL EXTRACT PARTIAL RECOVERY] complete_items=N` when later JSON is cut.
- `[AI JSON STRUCTURAL RECOVERY] prompts/social_extract.txt` after recovery.

## Verification

```text
python -m py_compile main.py balthasar.py companion_watch.py tools.py ui.py
python -m unittest -v tests.test_balthasar_companion_social_json_hotfix_v1_10_47_8
python -m unittest -v tests.test_companion_watch_v1_10_47 tests.test_balthasar_contracts
python -m unittest discover -s tests -q
```

This build includes IYF Companion Watch Hotfix V1.10.47.7.
