# Answer Audit Scope Anchor V1.10.15

Build: `bekki-answer-audit-scope-anchor-v1-10-15-20260829`

## Observed failure

After External AI answered `SNH48目前有哪些正式Team？`, the final Answer
Auditor received 16 web results. Its input grew from 43,200 bytes and was
middle-compacted to 27,851 bytes. The Auditor then treated an adjacent page
title, `SNH48成员列表`, as the user's request and rejected the candidate for
not listing every member. The correct lifecycle decision had already passed,
but no answer was shown and no Knowledge record was written.

## Changes

- `authoritative_user_request` and `candidate_external_answer` are the binding
  audit pair.
- `final_scope_anchor` repeats the exact request after all optional evidence.
- Web context is limited to six compact conflict excerpts. Full page bodies
  are excluded from the Answer Auditor.
- Web evidence may reveal a direct contradiction but cannot redefine the
  request, add facets, or change the completion target.
- High-impact certification context is summarized to whether certification
  occurred and which provider performed it; long prior answers and prompts are
  not duplicated in the audit packet.
- Audit strings are bounded by UTF-8 bytes before the normal model budget is
  applied.

No additional AI call, External-AI request, keyword classifier, SNH48 rule, or
Python fact judgment was added.

## Focused live tests

```powershell
$env:BEKKI_LIVE_AI_TESTS="1"
python -m unittest -v `
  tests.test_live_ai_contracts.LiveAIContractTests.test_current_formal_unit_set_fallback_lifecycle_contract `
  tests.test_live_ai_contracts.LiveAIContractTests.test_external_answer_audit_scope_anchor_contract
Remove-Item Env:BEKKI_LIVE_AI_TESTS
```
