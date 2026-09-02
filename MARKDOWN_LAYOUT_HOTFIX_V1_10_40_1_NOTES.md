# Markdown Layout Hotfix V1.10.40.1

Build ID: `bekki-markdown-layout-hotfix-v1-10-40-1-20260901`

This hotfix keeps the V1.10.40 safe-Markdown and evidence-card design while
repairing two failures found during live Windows testing.

- Rich user and Bekki bubbles are measured with `QTextDocument` at their real
  content width. The last user line is no longer clipped, and short Bekki
  replies no longer reserve a large blank vertical area.
- Message/card geometry refresh is queued onto the Qt event loop so the worker
  result handoff is not held by a synchronous full-layout recalculation.
- Recommendation recovery uses a fresh source batch. Results from a domain
  seen in pass one can therefore supply a different product in pass two.
- Recovery sources re-enter candidate generation and independent audit instead
  of becoming raw source cards immediately.
- An explicit budget may be checked using an independent editorial reviewed
  price or official MSRP/list price. Bekki still makes no live stock, seller,
  or checkout-price claim.
- If no product passes all hard conditions, Bekki returns a Markdown answer
  naming the rejected candidates and their evidence gaps. Any source cards are
  labeled as reading leads and are limited to the requested result count.

The local models, 8192-token context, persistent minimized Edge profile, and
16 GB GPU operating target are unchanged.
