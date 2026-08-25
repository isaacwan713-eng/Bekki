# Bekki Skills V1

## Runtime invariants

- AI owns intent, reference resolution, stage selection, semantic Skill match,
  adapter selection, destination selection, and compatibility review.
- Python owns closed enums, exact opaque IDs, lifecycle state, file-extension
  contracts, bounded destinations, durable storage, and local I/O.
- A complete current command is authoritative. Old context and pending work may
  not add an outcome to it.
- Ordinary Skill lookup can read only verified Skills. A pending candidate is
  reachable only through the exact ID carried by one active checkpoint.
- Folder opening, recommendation, and content installation are separate
  capabilities. Recommendations are never stored as Skills.
- No failed, blocked, interrupted, rejected, expired, or merely researched
  operation becomes verified.

## R19 runtime budget boundary

Melchior owns whether a turn is an ordinary `TASK` or genuine `COMPANION`
interaction and selects the smallest required context profile. Python validates
the closed values and applies resource limits; it does not infer product
features, recommendation criteria, or emotional intent. Balthasar runs only for
LOCAL_ANSWER companionship. Its separate execution-calibration generation is
not part of the task pipeline.

Ordinary self-contained prompts do not load conversation summaries, long-term
memory, document text, or image text. Follow-ups, explicit memory questions,
companionship, documents, and images receive their corresponding bounded
context. A valid reply is saved normally without running a second AI call to
summarize context.

The cached engine pair is ordered, not simultaneous: Google is primary for the
US profile and Bing is a fallback only when the current evidence stage receives
too few usable primary results. Python enforces the requested result budget and
deduplication; AI continues to own topic, criteria, candidate choice, and
candidate verification.

## First successful folder request

1. Context-scope AI returns `CURRENT_ONLY` or `NEEDS_CONTEXT`.
2. Stage AI returns `OPEN_FOLDER_ONLY`.
3. If no verified folder Skill matches, Bekki researches documentation for the
   reusable destination—not a particular tactic or mod.
4. A dedicated grounding AI verifies that the proposed application, content
   kind, scope, and reusable outcome are supported by the authoritative current
   request. A copied example or unrelated historical identity fails closed.
5. A focused query AI fills only missing documentation searches while
   preserving the accepted application, content kind, and scope. An independent
   AI review must accept those queries before browser discovery.
6. AI extracts a procedure, chooses a local adapter, selects one opaque local
   destination ID, and independently reviews the binding.
7. Python validates the selected adapter's declared file type, Skill scope, and
   destination kind before any local write or folder open.
8. Bekki opens the destination and records machine completion in a V2 pending
   candidate.
9. Bekki asks the user whether the folder is correct.
10. Only an AI-classified explicit acceptance commits the candidate to
   `data/skills.json`.

The second equivalent request goes directly through AI semantic matching over
verified Skill summaries and reopens the still-bounded destination. It does not
repeat web research.

## Install-content request

`INSTALL_CONTENT` is a different scope from `OPEN_DESTINATION_FOLDER`. The
first supported install request may learn the reusable method and ask whether
Bekki should continue. The continuation checkpoint carries one exact candidate
ID. Download and installation can run only for that candidate or for a verified
install Skill whose scope exactly matches the stage.

The current `FM_TACTIC` adapter accepts only a declared `.fmf` procedure and a
`fm_tactic_destination`. This is an execution contract, not a Python guess
about what the user meant. A `.jar`, another destination kind, or a folder-only
Skill cannot enter this installer even if an upstream model returns a bad
binding.

## V2 registry lifecycle

Pending and verified records use schema version 2. Required structural fields
include Skill scope, adapter, destination ID/name/kind/path, and expected file
types. Candidate keys provide exact deduplication. Skill IDs include scope and
adapter identity, so a folder Skill cannot overwrite an install Skill.

Legacy or malformed pending records are quarantined to
`data/invalidated_skills.json`; they are never repaired semantically or exposed
to Skill matching. Registry JSON uses atomic replacement, fsync, and a
last-known-good backup. Commit is idempotent across a crash between the verified
write and pending removal.

Machine completion is rejected when any protected event, approval request,
clarification, cancellation, or interruption flag is present. The reported
action and destination must exactly satisfy the candidate's scope.

## Context isolation

The user turn saved by the UI is structurally excluded from prior conversation
before routing, so the current request appears only once. For a standalone
request, all remaining prior context is removed before stage classification and
Skills lookup. A checkpoint relation AI separately distinguishes a real reply
from a complete new command; a new command neither resumes nor rejects the old
candidate.

## Browser learning boundary

Stable runtime localization defaults are cached in `data/location.json` for
seven days and refreshed early when the system time-zone/offset signature
changes. The profile supplies country, time zone, unit system, currency, and a
preferred search-engine pair. R21 intentionally supports only the user's main
US environment: Google is primary and Bing is the insufficient-results
fallback for both Chinese and English requests. Country codes and query language
cannot activate another search engine, and no model call is used to choose the
pair. Shopping and recommendation flows reuse the same pair for the task.
Windows location source, confidence, country and time-zone signals remain
available for localization and unit conversion, not engine selection.

For ordinary facts and product recommendations, R21 uses Google AI Overview
and indexed result snippets as a fast proposal layer. A separate adversarial
12B pass checks the proposal for category or audience drift, unsupported
conditions, stale periods, source disagreement, and contradictions. Original
pages are opened only for an identified evidence gap. High-risk facts and
shopping claims remain strict page-evidence workflows.

R22 keeps product-language localization AI-owned. The planner combines the
original wording, runtime region, and audience to choose natural market search
terms without a Python translation table. Recovery candidates are generated
only from the new recovery evidence and exact rejected titles cannot re-enter.

R23 gives exact-product purchase lookup its own lightweight path. When the
user names one product or explicitly refers to a previous option, the 12B AI
must preserve its complete brand/model identity. Search summaries only propose
purchase entries; a separate adversarial 12B pass rejects accessories, wrong
models, generic pages, and false merchants. Price and stock may remain UNKNOWN.
Open-ended category shopping continues through the comparison pipeline.

R24 applies one bounded resource contract across public-web research. Query
generation, source scoring, news extraction, news curation, product extraction,
shopping comparison, and final research summaries use `gemma3:12b` with
thinking disabled. News reads at most six ranked pages and never requests a 32K
extraction context. The final JSON parser also unwraps Markdown code fences
without changing the model's semantic answer.

R25 removes `gpt-oss:20b` from the entire runtime. Short closed decisions stay
on `llama3.2:latest`; conversation, learning, learned-skill reasoning, research,
recommendations, vision, and final writing use `gemma3:12b`. The shared model
boundary disables unsupported thinking modes for both compact model families.
This is a resource policy: AI still owns semantics while Python owns safety,
resource, format, and execution boundaries.

## Shopping evidence boundary

A complete shopping request is planned from the current turn only. Prior
shopping text is available solely when the request is explicitly referential.
Resolved state and long-term profile data do not generate product queries or
hard requirements.

If both compact shopping plans are unusable, Python may recover an executable
query solely when both attempts agree on the cleaned product category and a
separate compact check binds that category to an exact phrase in the
authoritative request while also confirming that every explicit
non-popularity constraint is represented. This boundary applies to both
shopping requests with or without popularity intent.
The shopping controller may additionally invoke a
narrow category-translation repair after both full plans fail. That compact
step copies one complete source category phrase and translates it without
choosing a brand, merchant, or preference. A second semantic check must accept
the translation and every explicit constraint before it can become a query.
Compound categories are indivisible at both planning and evidence stages:
generic cup evidence cannot satisfy straw cup, and generic headphones cannot
satisfy noise-cancelling headphones. This is a semantic rule, not a hardcoded
category catalog.
That compact check also protects referential plans: an explicit current-turn
category always outranks stale recent context, while recent context may supply
a category or grounded numeric/model-year constraint only when the current turn
truly omits it and refers back. Negated popularity and merchant phrases cannot
be promoted to positive hard constraints; multiple named merchants remain a
regional comparison because the single-merchant exclusive schema cannot
represent them safely.
Python supplies a closed evidence-oriented search phrase for the detected
shopping region: generic shopping research uses best-rated/high-review wording,
while explicit popularity intent uses the corresponding
viral/trending/mainstream/demand wording. It does not choose a brand or infer a
product preference. Category disagreement, an
untranslatable category, an added unowned modifier, or an ungrounded
requirement still fails closed. Recovery retains hard constraints only when
both plans independently ground them; numeric units, currencies, and comparison
directions must also agree with the source wording.

Product recommendation and shopping are separate evidence routes. A product
RECOMMENDATION_RESEARCH request ends with independent recommendation,
comparison, and expert-review evidence plus a candidate-specific category and
explicit-condition verification pass; it does not continue to known merchant
product pages. Only an explicit request to buy, check price or stock,
locate a seller, or obtain a purchase link enters SHOPPING_RESEARCH.

Ordinary product recommendations do not call `build_shopping_plan`. One capable
AI owns the complete recommendation topic, category translation, explicitly
stated criteria, audience scope, editorial search queries, eligible engine
choice, candidate-specific verification queries, result-count policy, recovery
queries, ranking, and final summary. A simple request for cups therefore searches
for cups without Python inventing size, material, brand, popularity, price, or
other feature requirements. A compound category such as straw cup remains an
AI semantic decision rather than a Python token gate.

The first AI pass may use search summaries, engine-generated overview-like text,
and opened independent reviews to discover exact candidate names. A second AI
pass checks each candidate against follow-up non-merchant sources. The candidate
must be the requested category and satisfy every explicit condition; an
unverified or contradictory option is rejected. If too few remain, AI creates
new discovery queries and Bekki performs one bounded recovery search before the
final answer.

Python's recommendation-path role is execution-only: bounded JSON parsing,
eligible-engine/catalog structure, public search and page reading, exclusion of
known merchant pages from the recommendation route, resource limits, duplicate
UI cleanup, and binding AI-cited source indexes to cards. It does not retranslate the
category, decide whether a source is semantically relevant, promote features,
apply popularity thresholds, rank products, or choose the requested count.
When a number is explicit the AI is instructed to honor it when evidence allows;
for vague words such as `几个` or `一些`, the AI chooses one to three without
padding. The final recommendation wording is written by that same AI from only
the candidates that pass the second-stage verification.

Routine Melchior routing uses `gemma3:12b`. This avoids loading the 20B runner
for a simple recommendation before the browser can start. The 20B model remains
available for deep conversation, learning, and larger reasoning work.

After Melchior routes a product recommendation, Bekki releases the 20B and
compact routing residents before loading the required `gemma3:12b` model.
Gemma owns the recommendation plan and source synthesis, using normal model JSON
with strict parsing and one retry. Those calls do not force Ollama JSON Schema.
This model handoff prevents repeated gpt-oss generations from exhausting or
crashing the 16 GB Windows CUDA runner. Gemma is released before Bekki returns
to later chat/context work. Malformed output cannot enter execution; it is retried once and then fails
closed without a Python semantic substitute.

An external browser AI may be used only as an explicitly enabled discovery or
summary assistant. Its claims are leads: Bekki must open the cited original
public review or comparison pages before presenting a recommendation. Price,
stock, seller, and purchase claims additionally require the separate shopping
route and a concrete product page. A signed-in browser assistant must never be
activated silently or treated as Bekki's final authority.

Explicit viral, trending, mainstream, well-known, popular, or best-selling
intent is preserved as a closed requirement. Brand candidates must be visibly
named by independent current discovery sources before Casper searches concrete
merchant pages for those brands. Product pages own price, stock, specifications,
ratings, and listing-level demand; they cannot alone prove that a brand is viral
or mainstream. Python verifies cited source text, enforces distinct brands and
current-turn requirements, and refuses unknown niche fillers. Returning one or
two supported cards is preferable to inventing or weakening a three-item answer.

The proposed learning plan and its documentation queries pass separate focused
AI reviews. Python checks only the JSON/list/bool contract. Empty discovery,
empty ranking, or no readable evidence stops before procedure extraction, so no
empty-page procedure can become a Skill candidate.

## Canonical runtime

Run from the project root:

```powershell
python main.py
```

The authoritative desktop modules and prompts are at the project root. The
first-level `casper` directory is the imported execution package. Do not run
the legacy mirrored `casper/main.py` or nested `casper/casper` tree.

## Verification

Deterministic suite:

```powershell
python -m unittest discover -s tests -v
```

Manual workflow after restarting Bekki:

1. Enter a complete command that only asks to open one application's content
   destination.
2. Confirm that no earlier search/install preference enters the request.
3. Verify the opened folder and answer that it is correct.
4. Rephrase the same folder-opening outcome and confirm that the verified Skill
   is reused without web learning.
5. Give a different complete command while a checkpoint is active and confirm
   that the new command runs without resuming or deleting the checkpoint.

Real Ollama behavior is intentionally tested separately from deterministic unit
tests. Required model tags are in `MODEL_REQUIREMENTS.json`.
