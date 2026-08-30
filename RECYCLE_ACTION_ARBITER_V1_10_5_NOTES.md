# Recycle Action Arbiter V1.10.5

Build: `bekki-recycle-action-arbiter-v1-10-5-20260829`

Baseline: Knowledge Correction V1.10.4

## Fixed behavior

- A self-contained current request such as `打开回收站` is authoritative even
  when an older conversation contains a restore request or unrelated answer.
- Casper compares its broad Recycle Bin action judgment with a focused
  restore-intent judgment.
- If those AI judgments disagree, an independent Gemma 4 arbiter selects the
  closed action contract: list, open, restore one item, unsupported, or
  clarify.
- Invalid arbitration fails closed to clarification. It cannot silently enter
  the restore-item selector.
- The current request now precedes old reference context in both focused
  restore classification and opaque item selection.
- No Python keyword or entity rule was added; AI owns the semantic decision
  while Python validates action tokens and confirmation boundaries.

## Verification

The deterministic suite includes adversarial old-chat regression coverage for
opening the Recycle Bin, disagreement arbitration, invalid-arbiter fail-safe,
and current-request prompt ordering. An opt-in real-model contract exercises
the same stale restore and unrelated-person context against the installed
Ollama models.

Run the targeted real-model contract in PowerShell:

```powershell
$env:BEKKI_LIVE_AI_TESTS="1"
python -m unittest -v tests.test_live_ai_contracts.LiveAIContractTests.test_recycle_open_ignores_old_restore_context_contract
```
