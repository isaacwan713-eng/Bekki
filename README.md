🩵 Bekki AI

Current installed source patch: **Stable V1.3.9.5** (`bekki-stable-v1-3-9-5-20260824`),
built on the last stable R25 UI and runtime. On startup the authoritative root
entry point prints this build ID and its full loaded path.

Stable V1.3.9.5 ranks every date-verified recent social candidate by the
single interaction value visibly shown on the search page before selecting the
strongest seven. The five-to-seven summaries and Top 3 cards therefore use the
same high-to-low order. Bekki explains this generic metric once instead of
repeating an unknown-type disclaimer on every result. Duplicate AI items for
one post title are accepted only once. The UI is unchanged.

Stable V1.3.9.4 captures one bounded screenshot from every opened social-post
detail page and binds each image to exactly one verified post title. The local
vision model can describe the post's main image and read likes, comments, and
shares only when a visible label or unmistakable icon is paired with its count.
收藏/bookmark counts can never become shares, ambiguous metrics stay unknown,
and the existing five-to-seven summaries plus Top 3 cards remain unchanged.
The UI is unchanged.

Stable V1.3.9.3 bounds social-vision output to prevent repeated OCR strings
from exhausting the JSON response before it closes. Chinese social requests
now carry an explicit Chinese narrative-language contract for image summaries
and post introductions while preserving copied titles, names, and evidence in
their original language. Labeled engagement evidence remains strict. The UI is
unchanged.

Stable V1.3.9.2 resolves recent Xiaohongshu titles across multiple bounded
virtualized search-result viewports instead of inspecting only the final scroll
position. Candidate links are also accumulated at every viewport. The final
social reply is rendered from the already grounded structured summaries, so
five-to-seven extracted items cannot be silently collapsed into three prose
mentions. Top cards remain capped at three and missing metrics remain unknown.
The UI is unchanged.

Stable V1.3.9.1 resolves the closed-route conflict observed when named social
research is about a recommendable product or restaurant. A request such as
searching Xiaohongshu for new McDonald's toys stays SOCIAL_RESEARCH; it cannot
also become RECOMMENDATION_RESEARCH + PRODUCT. The recovery remains AI-owned
and receives an explicit mutually exclusive contract. UI and the V1.3.9 social
ranking behavior are unchanged.

Stable V1.3.9 expands named social research to retain and briefly describe up
to seven recent posts. For grounded Xiaohongshu post pages, it reads only
visibly labeled likes, comments, and shares, ranks the candidates by their
visible interaction totals, and displays at most the strongest three cards.
If fewer than three metric-bearing posts are available, Bekki returns only
those available posts and never pads the result. Unlabeled search-grid counts
remain generic interaction signals rather than being mislabeled as likes.
Restaurant names remain unchanged, and missing images or links are acceptable.
The stable UI is unchanged.

Stable V1.3.8 closes the remaining fixed-follow-up evidence gap. An unrelated
page cannot produce evidence for a fixed restaurant unless its rendered body
literally contains that exact restaurant name. All fixed candidates remain in
the comparison even when one lacks a current clickable source, and Bekki may
give a clearly qualified practical family-dining judgment from confirmed menu,
dish, service, seating, atmosphere, and prior-turn evidence. Unverified high
chairs, accessibility, and child policies remain UNKNOWN. UI remains unchanged.

Stable V1.3.7 keeps follow-up comparisons such as “which of these three” bound
to the exact earlier candidates selected by AI from recent context. Query
review, retries, guides, extraction, and final selection may add evidence but
cannot substitute another restaurant. Restaurant names are hidden behind
opaque tokens while the final response is written and restored afterward, so
the writer cannot partially translate an English name. UI remains unchanged.

Stable V1.3.6 preserves restaurant, store, brand, and other candidate names
exactly as written by the evidence source. The final answer may not translate,
transliterate, localize, shorten, or invent another-language name. UNKNOWN
requirements remain explicitly unverified, and a search that verifies fewer
options than requested must state the verified count instead of implying that
the target was met. Search behavior and the stable UI are unchanged.

Stable V1.3.5 extends reliable MAGI's existing 12B judgment with a closed
search subtype and recommendation domain. An open-ended request for good
restaurants now goes directly to RECOMMENDATION_RESEARCH + RESTAURANT; the
compact Melchior model cannot reinterpret it as NEWS_FEED. News, one-fact,
claim-check, named social research, shopping, and other searches remain
distinct AI-owned outcomes. No Python keyword routing or UI change was added.

Stable V1.3.4.1 fixes the live Xiaohongshu result-grid structure observed after
V1.3.4. After timestamp validation, Bekki locates the complete visible post
title directly in the still-open page, climbs to the containing card for its
image and link, and uses a bounded click fallback when the card has no ordinary
anchor. The search page is restored after the fallback and the UI is unchanged.

Stable V1.3.4 turns grounded recent social posts into the existing UI result
cards. Bekki binds an extracted post title to its real platform link and image,
opens that post for visible details, and displays a short introduction beside
the image. A restaurant name is accepted only when its exact visible evidence
is present; missing child-suitability details remain explicitly unknown. The
stable UI files are unchanged.

Stable V1.3.3 makes Xiaohongshu queries platform-native Chinese, validates
visible timestamps against the requested recency window, and adds bounded
local visual understanding for up to three visible social-search frames. Image
observations are accepted only when they can be tied to a post title that
already passed the time filter; ambiguous and old-post images are excluded.

Stable V1.3.2 extends the existing reliable 12B MAGI result with a closed
AI-owned social-search scope and requested platform list. An explicit
X/Twitter, Instagram, or Xiaohongshu search goes directly to SOCIAL_RESEARCH;
the compact Melchior model cannot reinterpret it as NEWS_FEED. The same 12B
MAGI call is reused and released normally, so this adds no extra model call.

Stable V1.3.1 sends Melchior's AI-owned `FILE_ACTION` scope directly to the
bounded file executor, so the unrelated application/window planner cannot emit
prose or guessed paths first. A reliable 12B gate fixes the exact file action;
the detailed planner is schema-constrained to that action. Python scans the
real filesystem with strict limits and returns only observed paths.

Stable V1.2 keeps routing AI-owned and fixes reminder-list routing found in
live testing. Melchior now makes an independent first detailed judgment instead
of being schema-locked to MAGI's initial lane. A disagreement returns to the
reliable 12B MAGI auditor before one lane-constrained replan.

Stable V1.1 introduced the reliable MAGI and final JSON recovery foundation.
Reliable `gemma3:12b` MAGI chooses SEARCH, LOCAL, or COMMAND and is then
released. A result below 0.65 confidence is rejected as a contract failure and
receives one independent AI judgment from `gemma3:4b`; Python never selects a
lane by keywords.

All Ollama generation now passes through `model_runtime.py`: UI and scheduler
processes share one model mutex, another loaded model is released before a
switch, 12B context is capped at 8192, oversized UTF-8 prompts retain their
instruction prefix and current-request suffix, and CUDA/HTTP 500 failures get
one cleanup retry. Recommendation failures preserve already-found independent
sources instead of returning an empty screen. Final replies are schema-bound;
malformed JSON receives one 12B format-only recovery, then a display-only safe
extraction that never restores actions or memory. Stable V1.1 does not modify
`ui.py`.

R25 removes `gpt-oss:20b` from every runtime path. In Stable V1.1,
`gemma3:12b` owns reliable MAGI judgment plus conversation, learning, research,
vision, verification, and final writing; `gemma3:4b` handles compact Melchior
routing; `llama3.2:latest` remains limited to bounded auxiliary decisions. The
common model boundary disables unsupported thinking levels, preventing Gemma
HTTP 400 errors and avoiding a 20B runner on the user's 16 GB GPU.

The reissued R25 uses one compact default behavior prompt plus a separate
final-reply persona prompt. Search, routing, audits, safety, and execution do
not load companion personality. Ordinary answers, current facts, news,
restaurants, and product recommendations use Bekki's light virtual-idol voice;
companionship uses her full expressive persona together with Balthasar. The
persona never changes evidence and automatically becomes restrained for
serious or high-risk topics.

R24 established the bounded 12B research pipeline. News, facts, claims, product
research, and shopping comparison use `gemma3:12b` with thinking disabled.
News extraction is capped at six ranked pages and a bounded context. Final
research replies accept both plain JSON and Markdown-fenced JSON.

R23 separates a named-item purchase request from open-ended shopping. The 12B
AI resolves a complete product title from the current request or an explicit
recent reference, searches direct purchase entries, and uses an independent
12B audit to reject accessories, wrong models, and non-purchase pages. Missing
price or stock is reported as UNKNOWN instead of discarding a valid merchant.

R22 keeps Python out of product translation. The recommendation planning AI
uses the original wording, US runtime profile, and audience to choose natural
US market terms rather than literal dictionary translations. Recovery candidate
generation sees only newly discovered evidence and cannot reselect an exact
title that was already rejected.

R21 uses Google AI Overview and search-result snippets as a fast first-pass
research layer for product recommendations and ordinary factual questions. A
separate adversarial 12B AI checks category, audience, explicit constraints,
time scope, source agreement, contradictions, and unsupported claims. Source
pages are opened only when that auditor identifies a real evidence gap. High-
risk facts and shopping claims such as price, stock, and exact specifications
continue to use strict page evidence.

R20 keeps R19's runtime reductions and intentionally limits active public-web
discovery to Google and Bing for the user's US environment. Both Chinese and
English requests use Google first; Bing runs only when Google evidence is
insufficient. No model is called to select a search engine.

R19 keeps R18's weekly `data/location.json` cache and removes avoidable work
from each turn. Melchior now selects TASK or COMPANION plus the smallest needed
context profile. Ordinary questions, recommendations, research, and actions
skip Balthasar; emotional companionship retains it. Final prompts use bounded
4K-8K contexts, and Bekki no longer runs an extra AI context-summary call after
a valid reply. Google is primary and Bing is used only when Google results are
insufficient.

R18 created `data/location.json` on first startup and refreshes it weekly or
when the system time-zone signature changes. It caches country, time zone, unit
system, currency, and Google/Bing search defaults for a US Windows profile so
these stable facts do not require a new model decision on every request.

Bekki is a local desktop AI companion created and maintained by YW49. It is built with Python, PySide6, Ollama, and local language models.

It is designed around a simple principle:

AI handles understanding and semantic decisions; Python handles deterministic execution, state, and tools.

Canonical runtime tree

Run Bekki only from the project root with `python main.py`. The authoritative
desktop entry point, shared modules, prompts, tests, assets, and build spec are
the root-level files and folders. The first-level `casper/` directory is the
authoritative Casper package imported by root `main.py`.

Do not run `casper/main.py`, change into `casper/` before launching, or build
from `casper/Bekki.spec`. Those mirrored files are retained temporarily for
compatibility and are not a second supported runtime. Changes must be made in
the authoritative root tree and, where an intentional compatibility mirror is
still present, protected by a drift test.

Bekki is not just a chat window. It can retain useful context, remember selected user preferences, search the web when needed, read local files, and understand images or screenshots.

V1 features

Local AI chat through Ollama

Conversation context for references such as “that”, “it”, and “today”

Memory for selected profile, preference, relationship, and temporary facts

Web-search pipeline with AI search decisions and evidence passed back to the main model

Local document reader for PDF, DOCX, TXT, MD, CSV, and XLSX

Document overview and retrieval modes, selected by an AI document router

Image and screenshot understanding for PNG, JPG, JPEG, and WEBP

User-triggered Desktop Reading for the primary display, active window, or a selected screenshot region through the local Vision model

In-app thumbnail previews for uploaded images and every Desktop Reading capture

PySide6 desktop interface with file/image attachment cards and live activity status

Windows desktop build through PyInstaller

How Bekki chooses a source

User need

Primary source

Personal preferences or past conversation

Memory / conversation context

Question about the active local document

Document reader

Question about the active image or screenshot

Vision model

Current or changing information

Web search

Document claim that needs current verification

Document reader + web search

Requirements

Windows 10/11

Python 3.10+ for development

Ollama

Microsoft Edge for Casper's managed public-web browser

NVIDIA GPU recommended for a responsive local experience

The current runtime requires these local models:

ollama pull gemma3:12b
ollama pull gemma3:4b
ollama pull llama3.2:latest

`llama3.2:latest` handles bounded compact local-action contracts.
`gemma3:12b` handles chat, learning, learned Skills, image understanding,
research, recommendation planning, candidate verification, recovery, and final
synthesis. `gemma3:4b` is reserved for the bounded HoYoPlay screenshot check so
the launcher does not need to load the larger model merely to locate one verified
button. `gpt-oss:20b` is not required or called by Stable V1. Set `VISION_MODEL` or
`HOYOPLAY_VISION_MODEL` only when intentionally using another installed Vision
model. The machine-readable source of truth is `MODEL_REQUIREMENTS.json`.

Development setup

git clone <your-repository-url>
cd AI-Assistant
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py

Always run the last command from the project root. A quick model check is:

ollama list

The rendered-browser content workflow does not require a search API key. Create
a `.env` file only if you also want the optional Brave API fallback used by
legacy/general search paths:

BRAVE_API_KEY=your_key_here

Keep .env private. Never commit or share it.

Skills lifecycle

The implementation and Windows acceptance checklist are documented in
`BEKKI_SKILLS_V1.md` and `BEKKI_OPTIMIZATION_REPORT_20260818.md`.

Casper may reuse a local device procedure only after the AI selects a compatible
skill by its supplied opaque ID. A newly learned procedure first enters pending
state; it does not become a verified Skill merely because research or file
placement succeeded. Python then performs bounded machine checks and Bekki asks
the user to verify the observed result. Only explicit acceptance after successful
execution commits the candidate to `data/skills.json`. Rejected, failed, expired,
or abandoned candidates never become verified Skills.

Content-learning checkpoints, browser handoffs, and user-verification prompts
remain pending for 24 hours. Other pending actions, including device approvals,
expire after 15 minutes. These are deterministic lifecycle bounds, not semantic
judgments.

Tests

Run the full deterministic suite from the project root:

python -m unittest discover -s tests -v

The runtime-contract tests specifically verify canonical import resolution,
root/mirror memory drift, pending-action TTLs, recoverable atomic JSON writes,
current-turn exclusion from recent context, and the documented Ollama model
manifest:

python -m unittest -v tests.test_runtime_contracts

These tests use fixed contracts and do not claim that Ollama is installed or
running. Check `ollama list` and perform a real smoke request before release.

After installing all dependencies and models, run the opt-in real-model
contracts in PowerShell:

```powershell
$env:BEKKI_LIVE_AI_TESTS = "1"
python -m unittest -v tests.test_live_ai_contracts
Remove-Item Env:BEKKI_LIVE_AI_TESTS
```

The content workflow uses Casper's rendered browser with one fixed US-oriented
pair: Google first, Bing only when Google returns too little usable evidence.
Chinese and English requests use the same pair. Search-engine choice no longer
loads a compact model, and regional engines are outside the active runtime.
Shopping and recommendations reuse the pair for the whole request. A
dedicated AI checks that each learned plan is grounded in the current request,
then a separate AI reviews its documentation queries before browser discovery.
Recommendations are not stored in Skills. Product recommendations isolate a
complete new request from old product context and end at grounded independent
review, comparison, or recommendation pages. They do not open merchant or
product-detail pages merely because the subject is a product. Explicit viral,
mainstream, or popular-brand requests require current support from independent
sources, and Bekki returns fewer than three rather than filling a slot with an
unsupported niche brand. Merchant listings, price, stock, seller, and purchase
links belong only to an explicit shopping request. On that separate route,
unknown merchant domains must expose structured Product data before they can
produce a shopping card.

Use the Windows app

After packaging, open:

dist\Bekki\Bekki.exe

Keep the full Bekki folder together. The executable needs the bundled assets, prompts, and configuration files beside it.

Build a Windows release

Install PyInstaller once:

pip install pyinstaller

Then build from the project root using the only supported specification:

pyinstaller --noconfirm --clean Bekki.spec

For troubleshooting, temporarily set console=True in Bekki.spec to keep a terminal log visible.

Sharing with another person

Do not send only Bekki.exe; zip and share the entire dist\Bekki folder.

The recipient must install Ollama and download the models themselves. Do not
distribute your own `.env`, because it may contain private API keys. They can
create their own `.env` if they want the optional Brave API fallback; the
rendered-browser content workflow works without it.

V1 limits

One active document at a time

No OCR for image-only PDFs yet

Local-model speed and quality depend on the recipient’s GPU and available VRAM

Vision is single-image analysis, not continuous screen monitoring

Desktop Reading only captures after an explicit click and does not continuously monitor the screen

The optional Brave API fallback requires the user’s own key; rendered-browser
content discovery does not

Project roadmap

V1 — Complete

Reliable local chat, memory, context, search, documents, vision, polished UI, and a Windows desktop build.

V2 — MAGI Core and desktop companion

Single-model MAGI routing, persona/research/reasoning profiles, multi-session chat history, and a state-driven desktop companion.

MAGI V2 execution architecture

- Balthasar observes the user's emotional state, memory, profile, and explicit preferences.
- Melchior decides what result is needed and selects the response mode.
- Balthasar calibrates execution style without changing Melchior's factual goal or safety requirements.
- Casper executes the plan through supervised adapters for search, tasks, notifications, and Desktop Reading.
- Python enforces immutable validation, confirmation, and human-handoff boundaries.

Protected events such as CAPTCHA challenges, final payment, credential requests, deletion, and permission escalation must stop for explicit human control. Existing tools remain behind compatibility adapters during the Casper migration so they can be replaced incrementally without breaking stable features.

Casper Browser Phase 1

FACT_LOOKUP now uses a separate, headless Microsoft Edge profile managed by Casper. It discovers candidates through the rendered browser, opens and reads authoritative pages, and automatically tries the next candidate when a normal page cannot be read. Brave Search is retained only as a fallback when the managed browser cannot start or discovers no results. CAPTCHA detection stops execution for human control instead of switching channels to bypass the challenge.

Casper Browser Phase 2

When the first FACT_LOOKUP pass produces only null or AI-rejected candidates, an Evidence Gap Planner AI decides whether a materially different follow-up investigation is useful. Casper may execute one bounded follow-up round with at most two AI-written queries, then sends all evidence to the Evidence Judge and Answer Writer AIs. Python enforces only the query count, retry budget, contracts, timeouts, deduplication, and protected-event boundaries.

V3 — Multi-model MAGI

Independent specialist agents, evidence comparison, and a MAGI judge for complex decisions.

Author and ownership

Created and maintained by YW49.

Copyright © 2026 YW49. All rights reserved.
