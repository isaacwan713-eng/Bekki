# External AI Answer Anchor V1.6

Build: `bekki-external-ai-answer-anchor-v1-6-20260827`

## Fixed failure

ChatGPT Desktop could remain above the bottom of a long conversation. The old
adapter saved only currently visible text before sending. If viewport movement
then revealed an older off-screen answer, that old text looked new and could be
returned for the current NERV question.

## Current-turn anchor

Bekki now snapshots the complete UI Automation text and Copy-control inventory
before sending. During response polling it must observe the exact outbound user
prompt in UIA document order. Only assistant text after that prompt can become
the current answer.

An increased Copy-control count is also insufficient by itself: the current
prompt anchor must already be present. The exact new Copy control is scrolled
into view through UIA before invocation, without coordinates.

If no exact current-turn prompt anchor or readable following answer appears,
the adapter returns a timeout and leaves the Curiosity Journal unverified. It
never falls back to an older response.
