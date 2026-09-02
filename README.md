🩵 Bekki AI

Current installed source patch: **Verified Video Site + Companion Bridge Hotfix V1.10.47.3**
(`bekki-verified-video-site-bridge-hotfix-v1-10-47-3-20260902`), built on
Companion Watch Switch Hotfix V1.10.47.2,
Companion Watch Recognition Hotfix V1.10.47.1, Companion Watch V1.10.47,
Media Watch Native Discovery Hotfix V1.10.46.1,
Inline Social Video Theater + Watch Search V1.10.46,
Inline Social Video Audio Policy Hotfix V1.10.45.1,
Inline Social Video Audio + Bekki Fullscreen V1.10.45,
Inline Social Video WebView2 Lifecycle Hotfix V1.10.44.1,
Inline Social Video WebView2 V1.10.44, Inline Social Video
Compatibility Hotfix V1.10.43.1, Inline Social Video V1.10.43,
YouTube Recency and Channel Hotfix V1.10.42.1,
YouTube Social Evidence V1.10.42,
Discussion Extract Resilience V1.10.41.8.2,
Xiaohongshu Evidence Hotfix V1.10.41.8.1, Discussion Feed V1.10.41.8,
Social Claim Grounding V1.10.41.7,
User Message Completeness V1.10.41.6, Responsive Conversation Width V1.10.41.5,
Bilibili Video Evidence V1.10.41.4,
Social Evidence Binding V1.10.41.3,
Social Visual Resilience V1.10.41.2,
Social Price Grounding Hotfix V1.10.41.1, Unified Result Blocks V1.10.41,
Markdown Layout Hotfix V1.10.40.1,
Markdown Evidence V1.10.40, Social Evidence Package
V1.10.39, Social Evidence UI
V1.10.38, Social Comprehension V1.10.37,
Social Context Budget V1.10.36,
Bilibili First-Load Retry V1.10.35,
Unified Browser V1.10.34,
Bilibili Native Response V1.10.33,
Bilibili Render Recovery
V1.10.32, Bilibili Card-First DOM V1.10.31,
Bilibili Visible
Results V1.10.30, Social Relevance
Scope V1.10.29, Bilibili and Reddit Social Search V1.10.28,
Screenshot Multipass OCR V1.10.27, Screenshot
Current Evidence V1.10.26, Screenshot OCR
Fusion V1.10.25, Screenshot Local
Route Contract V1.10.24, Completed
Historical Milestone Knowledge V1.10.23.2,
Curiosity Foundation
Draft Calibration V1.10.23.1, Curiosity Native Knowledge
and Idle Exploration V1.10.23, Historical Snapshot
Lifecycle Calibration V1.10.22.1, Knowledge Intake and
Curiosity Breadth V1.10.22, Curiosity Foundation
Calibration V1.10.21, Knowledge Breadth and Historical Snapshots
V1.10.20, Knowledge-Aware Routing
and Adjacent Curiosity V1.10.19, Audit Finding
Normalization V1.10.18, Core Claim Isolation V1.10.17, Audited Core Answer
V1.10.16, Answer Audit Scope Anchor
V1.10.15, Nonstructural Lifecycle Boundary
V1.10.14, Fallback Lifecycle Basis V1.10.13,
Structure Lifecycle Authority V1.10.12,
Language-Safe Knowledge Review V1.10.11,
Semantic Grounding V1.10.10, Source Taxonomy &
Knowledge Lifecycle V1.10.9, Focused Certifier Calibration V1.10.8, Query
Certifier Calibration V1.10.7, Focused
Query Set V1.10.6, Recycle Action
Arbiter V1.10.5, Knowledge Correction V1.10.4, Daily Knowledge Curator
V1.10.3, and AI Fact Entity Scope
V1.9.6.2 and External AI Fact Fallback
V1.9.5.1 and Objective Fact Verification
V1.8, NERV Curiosity
Soft Gate V1.7, External AI Answer
Anchor V1.6, Knowledge Clusters V1.5,
News Feed Reliability V1.4,
Screenshot Search V1, UI Personalization V1,
NERV Knowledge Verification V1.4, External AI Desktop V1.3.2, NERV Learning V1.3, and
Stable V1.3.9.5. On startup the
authoritative root entry point prints this build ID and its full loaded path.

Verified Video Site + Companion Bridge Hotfix V1.10.47.3 separates a domain
named in a watch request from a website Bekki has actually verified as a video
source. An unfamiliar literal domain is opened in the managed browser and must
show repeatable same-site video detail pages plus video taxonomy or real media
structure. User wording alone never registers it. A rejected site stops before
the general web-search fallback, so an ordinary page cannot be presented as a
watch result merely because its URL contains `watch` or `video`.

Verified sites are stored in the preserved local data directory with their
observed same-domain search URL and public display aliases. For example,
`iyf.tv` can learn its native `/search/{query}` route and return the exact
`名侦探柯南` show page. Verification means the site is a discoverable video
source; it does not falsely grant inline theater compatibility, so a source
without a supported player contract remains an honest link-only card.

This build also replaces raw WebView2 messages in Bekki Companion Watch with
qtwebview2's `DictJsBridge` RPC contract. Companion messages no longer enter
the library's internal message parser as bare JSON strings, eliminating the
`TypeError: string indices must be integers` bridge traceback. This build
includes V1.10.47.2.

Companion Watch Switch Hotfix V1.10.47.2 makes playback ownership exclusive
across result cards and Bekki theater mode. Starting a second video first mutes
and calls native WebView2 `Stop()` on the previous player, detaches its event
handlers, and disposes its view before the new player is created. If the old
player cannot confirm it stopped, the new player is not started. Late WebView2
initialization from a superseded card is quarantined so it cannot resume in the
background. Switch, stop, theater, and audio logs now include video IDs for
clear runtime verification. Plainly exiting theater still returns the current
player to its card without stopping it. This build includes V1.10.47.1.

Companion Watch Recognition Hotfix V1.10.47.1 prevents direct conversation
from postponing Bekki's proactive deadline. The first usable-scene reaction is
attempted about eight seconds after enabling companion mode; later static
frames remain deduplicated. Direct questions now use `gemma4:12b` with a
higher-detail frame of up to 1280×720 at JPEG quality 84, while background
reactions retain the lightweight `gemma4:e4b` path. The answer prompt requires
concrete visible cues, honors user corrections, and no longer bounces an
observation question back to the user. WebView messages are JSON strings, which
removes qtwebview2's misleading `invalid message` diagnostic. Frame size and
encoded size are logged as `[COMPANION WATCH FRAME]`. This build includes
V1.10.47.

Companion Watch V1.10.47 adds an opt-in `Bekki 陪看` control to theater mode.
It opens a collapsible conversation panel over the lower-right of the active
YouTube or Bilibili video, so the user can type and receive replies without
leaving the player or writing into the main chat history. Bekki may also make a
short, low-frequency reaction when the visible frame meaningfully changes.
This first version reads pixels and the verified card title only; it never
claims to hear video audio. Static/paused frames are perceptually deduplicated,
the low-load `gemma4:e4b` model is serialized behind normal requests and NERV,
and session generations discard replies after the user exits theater, stops
playback, or switches videos. The panel is off by default. This build includes
V1.10.46.1.

Media Watch Native Discovery Hotfix V1.10.46.1 searches Bilibili and YouTube
on their native rendered search pages before using a general web engine. A
valid native video card is scored and selected directly; Google/Bing is used
only when native discovery returns no relevant result. Bilibili's structured
search response now preserves the real title, description, author, date, and
cover for the watch card. Explicit site conditions remain hard boundaries, and
generic media suffixes such as `视频` can be removed for a bounded subject match
(`下饭视频` may match a title containing `下饭`) without admitting unrelated
results. This build includes V1.10.46.

Inline Social Video Theater + Watch Search V1.10.46 adds `MEDIA_WATCH`, a
dedicated search outcome that stays separate from news, claim checks, and
social-post research. A named website is a hard condition: `去 B 站找一个下饭
视频` searches only Bilibili, randomly selects one relevant playable result,
and `换一个` excludes the prior URL. Named works use exact selection and fail
closed instead of substituting commentary, clips, trailers, or unrelated
videos. Without a named site, Bekki searches supported watch sources and
prioritizes Bilibili/YouTube pages it can play inline. Unsupported sites remain
honest link-only results.

Each playable result asks whether to enter theater mode. Replying `可以` or
clicking `影院模式` moves the existing WebView2 player into a dark layer inside
the same Bekki window; it does not open another page or restart the video.
Playback position and audio are preserved, only one player remains active,
Esc exits theater before exiting Bekki fullscreen, and the theater toolbar can
stop playback or toggle whole-window fullscreen. Cards are still paused until
the user explicitly starts or approves playback. This build includes
V1.10.45.1.

Inline Social Video Audio Policy Hotfix V1.10.45.1 configures WebView2's
Chromium runtime with `--autoplay-policy=no-user-gesture-required` before the
first browser environment is created. Bekki still creates a player only after
the user deliberately clicks `在 Bekki 播放`, and navigation remains bound to
the verified YouTube/Bilibili player. This bridges the native Qt click to the
browser media policy so Bilibili can start audible playback instead of staying
at `muted=false, playing=false`. Audio state is rechecked at 250 ms, 1 second,
and 2.5 seconds for slower iframe startup. This build includes V1.10.45.

Inline Social Video Audio + Bekki Fullscreen V1.10.45 explicitly requests
unmuted Bilibili playback after the user clicks `在 Bekki 播放`. It sets the
documented Bilibili `muted=0` player parameter, clears WebView2's global mute
state during initialization and after the embedded player loads, and logs the
observable WebView2 audio state as `[INLINE VIDEO AUDIO]`. Cards remain static
and paused until clicked. Bekki also gains a header fullscreen control plus
F11 to enter or leave fullscreen and Esc to exit, while preserving the prior
normal or maximized window state. Sidebar and task-drawer toggles no longer
shrink a maximized/fullscreen workspace. This build includes V1.10.44.1.

Inline Social Video WebView2 Lifecycle Hotfix V1.10.44.1 fixes switching away
from a video card that Qt has already destroyed. The active-player slot now
checks the underlying C++ object's validity, card destruction clears stale
references, and every stop/restore operation safely tolerates repeated cleanup
or already-deleted child widgets. A stale prior card can no longer block the
next YouTube or Bilibili player. This build includes V1.10.44.

Inline Social Video WebView2 V1.10.44 replaces the codec-limited QtWebEngine
player with one Edge WebView2 backend shared by YouTube, YouTube Shorts and
Bilibili. A virtual Bekki HTTPS wrapper gives YouTube a verifiable parent
referrer, while the installed Edge runtime supplies the normal browser media
codec stack required by Bilibili. Players remain absent until clicked, only one
card can play at once, and stopping restores the evidence cover. Main-frame
navigation, popups and downloads are blocked; the separate `打开原帖` action is
unchanged. The preserved WebView2 profile also provides the common browser
surface needed for a later Bekki co-watching state layer. This build includes
V1.10.43.1.

Inline Social Video Compatibility Hotfix V1.10.43.1 attempted to fix YouTube embed error
153 by loading the verified player inside a referrer-bearing iframe wrapper,
adding YouTube `origin` and `widget_referrer` identity, and preserving the
platform Referer on iframe and media requests. It removes QtWebEngine's product
token from the otherwise native Chromium user agent to avoid false unsupported-
browser detection. Bilibili receives the same persistent Referer handling.
Each play attempt logs H.264, VP9 and AV1 support as `[INLINE VIDEO CODECS]`, so
a Qt build without a required proprietary codec is distinguishable from a page
identity failure. This build includes V1.10.43.

Inline Social Video V1.10.43 adds lazy, in-card playback for verified YouTube
videos, YouTube Shorts and Bilibili videos. Every result remains a static cover
until the user clicks `在 Bekki 播放`; the player then replaces that card's
preview without opening a new page. Starting a second video stops and disposes
the first player, while `停止播放` restores the original evidence images.
Shorts use a bounded vertical surface and standard videos follow the responsive
card width. Player popups and main-frame navigation outside the verified embed
are blocked, the session uses memory-only cookies/cache, and `打开原帖` remains
an explicit separate fallback. This build includes V1.10.42.1.

YouTube Recency and Channel Hotfix V1.10.42.1 fixes explicit recent-channel
requests such as `去油管找最近 7 天 @aespa 的 Shorts`. YouTube's `New` badge is
no longer treated as a timestamp or rejected before detail inspection. An
undated grid card proceeds provisionally to its exact video, then survives only
when the opened video's publication metadata falls inside the requested
window. A missing or out-of-window opened date fails closed.

An exact `@handle Shorts` query now opens the channel-owned Shorts tab rather
than the general search grid. The opened video's channel handle must match the
requested handle, and the real opened-video channel replaces any model-authored
search-card author. Third-party Shorts that merely mention the artist in a
title, hashtag, or @mention are excluded. This build includes V1.10.42.

YouTube Social Evidence V1.10.42 adds YouTube/油管 as a first-class native
`SOCIAL_RESEARCH` platform alongside Bilibili. Literal search terms, channel
names, `@handles`, video IDs and an explicitly requested `Shorts` facet remain
unchanged. Search discovery accepts only rendered video, Shorts and live-video
cards; channel pages, playlists, search/navigation links and unrelated watch
links fail closed. Standard watch URLs, Shorts URLs, live URLs and `youtu.be`
short links resolve to bounded canonical video targets. A first empty YouTube
result render receives one same-tab reload, while a bounded cookie-choice
interstitial may be dismissed without touching sign-in controls.

Opened-video evidence is isolated to the current video's title, channel,
publication date and description from YouTube player/microformat metadata.
Recommendations, comments, neighbouring Shorts and page chrome are excluded.
Each card may show the native video thumbnail plus at most one decoded,
non-black, distinct player frame; ads and full watch-page screenshots are never
used as video evidence. The same rules apply to Shorts. An opened ISO
publication date overrides a conflicting relative search-card inference before
an explicit recency window is enforced. This build includes V1.10.41.8.2.

Discussion Extract Resilience V1.10.41.8.2 prevents one long or malformed
discussion-source JSON object from erasing an otherwise successful cross-site
roundup. Selected pages are extracted in batches of at most two. A truncated
array keeps every fully closed source object, and only missing source indices
are retried individually with compact evidence. A source that still fails is
omitted without discarding other batches, so readable Zhihu, Tieba, forum, Q&A
and indexed-post evidence can still produce the answer and its bound cards.
Pairing identities explicitly grounded by the sources are named once in the
synthesis. NERV Curiosity may not split a two-character fandom pairing into
“two words” or ask again for identities already stated by a grounded reply.
This build includes Xiaohongshu Evidence Hotfix V1.10.41.8.1.

Xiaohongshu Evidence Hotfix V1.10.41.8.1 makes the visible post detail the
authority for dates and media. Detail labels such as `Feb 22` or `4天前`
override a search-card date inferred from `昨天`; a conflicting result outside
the requested recency window is removed instead of being relabeled as recent.
Each inspected result must also pass a structured entity, category, and
relation gate before it can reach summaries or cards. A bounded variant remains
valid (for example, a larger insulated cup or another aespa member's Nongshim
photocard), while a generic Winter card without the Nongshim relation and a
plush keychain in a photocard search are excluded. Xiaohongshu cards now retain
only clear, non-placeholder media from the opened post. Native video posts add
up to two distinct non-black player frames; blurred preview images and generic
page screenshots are omitted. This build includes Discussion Feed V1.10.41.8.

Discussion Feed V1.10.41.8 adds a dedicated `DISCUSSION_FEED` route for open,
cross-site summaries of forum threads, Q&A pages, fan discussions, Zhihu,
Quora, Tieba and web-indexed posts. A closed question such as “卡黄闹翻了吗？”
remains `CLAIM_CHECK`; a mixed question such as “卡黄是闹翻了吗，她们为什么
会闹翻？” is led by its open causal-summary requirement and uses
`DISCUSSION_FEED`, never 3→5→7. Explicit supported native platforms such as
Bilibili, YouTube, Xiaohongshu and Reddit still use `SOCIAL_RESEARCH`. Discussion pages
are read separately, their attributed explanations and disagreements are
synthesized without a consensus vote, and each selected source keeps its own
context, optional page image and link card. Repeated community claims are not
promoted to confirmed facts. This build includes V1.10.41.7.

User Message Completeness V1.10.41.6 adds a small measurement guard to
naturally sized user bubbles. Chinese characters and other glyphs that Qt
measures a few pixels too narrowly now receive extra horizontal room; when a
message is near its responsive maximum, height is measured against a slightly
narrower safe content width so the final character wraps instead of being
clipped. Assistant responsive sizing and evidence-card widths are unchanged.

Responsive Conversation Width V1.10.41.5 makes the assistant reply and its
bound result cards react to the live chat viewport. The 350 px compact layout
is preserved for ordinary windows, while wide or maximized windows scale the
conversation column up to 760 px. Card context, screenshots, video covers and
sampled frames reflow together instead of leaving most of the window empty;
short user bubbles remain compact. Curiosity Writer output now has enough
generation budget to finish its schema-bound JSON and retries one truncated
response. A parse failure is reported as `writer_invalid_output` instead of
the misleading `no_curiosity`; that latter reason is now reserved for an
intentional `proposal=null` decision.

Bilibili Video Evidence V1.10.41.4 replaces generic video-page screenshots
with bounded video evidence. Each Bilibili card prefers the native cover and
adds at most one decoded player frame only when it is non-black and distinct;
black/loading frames are discarded. The former full-page `正文` thumbnail is no
longer shown. Video text is bounded to current title, UP author, publication
time and description, excluding the related-video rail. A cover or sampled
frame is never treated as a transcript or complete video summary. Xiaohongshu,
Reddit, the persistent minimized browser profile, model sizes and context
budgets are unchanged.

Social Evidence Binding V1.10.41.3 isolates the currently opened
Xiaohongshu note from related-post shelves before any local-model summary is
generated. Once title-bound post screenshots are available, Bekki skips the
lower-value search-page overview vision pass in every social ranking mode,
not only PRICE mode. Only resolved post titles enter the final per-post
summaries and cards when grounded targets exist. Repeated OCR/model runs such
as the same card label dozens of times are collapsed before display. A card
whose link is only a platform search page now says “查看搜索页”, while a concrete
post URL keeps “打开原帖”; search-preview evidence remains explicitly labeled.
The model, 8192-token social context, screenshot limits, minimized persistent
browser profile, and 16 GB VRAM coexistence target are unchanged.

Social Visual Resilience V1.10.41.2 keeps social evidence usable when a
foreground game leaves too little VRAM for an optional vision request. PRICE
searches no longer run the low-value search-page overview vision pass, and any
remaining overview failure is non-fatal: title resolution, post screenshots,
text extraction, deterministic price parsing, cards, and links continue. A
fresh-DOM reader can recover Xiaohongshu result cards even when reactive nodes
detach. Marketplace forms `30👝`, `35🍞`, `均7/1`, and `330💼` are retained as
prices with an unknown currency, and `柚小卡` joins the request-scoped Karina
alias group. Price-image response fields are bounded to avoid truncated JSON.
Generic platform search pages are no longer rendered as duplicate empty
“小红书” or Reddit cards. The model remains `gemma4:12b`, social context stays
at 8192 tokens, and screenshot limits and the persistent browser profile are
unchanged.

Social Price Grounding Hotfix V1.10.41.1 separates visible search-page
interaction counts from prices throughout PRICE-mode social research. A value
such as the `8` beside a Xiaohongshu result can no longer become a price merely
because a duplicated title begins with “出”; price cards and price rankings now
require a grounded price observation. Unknown-currency marketplace shorthand
such as `330💼`, `卡价 250`, and `1.9k` remains valid. The request-scoped verified
alias group for Karina also recognizes the platform-native names 柳智敏、柚卡
and 纯柚 without allowing the model to invent other identity aliases. Reactive
Xiaohongshu title clicks get one fresh-DOM recovery attempt. PRICE summaries are
deterministic, do not repeat per-post values already owned by cards, and state
clearly when no verifiable price was read. Model sizes, the 8192-token social
context, screenshot limits, and the 16 GB GPU operating target are unchanged.

Unified Result Blocks V1.10.41 removes the duplicated recommendation or post
list from the main Bekki bubble whenever matching result cards exist. The main
bubble now keeps only the overall conclusion or cross-result synthesis. Each
recommendation or social result owns its complete explanation, supported
strengths and tradeoffs, matching image or placeholder, and matching source
link in one ordered card. Social synthesis findings are bound by the original
post title even when the visible card title is a restaurant or product name.
The same card-first contract is included in both full and lightweight final
response prompts for ordinary search, recommendation search, and social
research. Model sizes, the 8192-token social context, screenshot limits, and
the 16 GB GPU operating target are unchanged.

Markdown Layout Hotfix V1.10.40.1 measures rich Markdown with the same Qt text
document used to render it. User bubbles keep their compact width without
clipping the final line, Bekki bubbles are top-aligned without large blank
areas, and expensive whole-message geometry refreshes are deferred until the
result handoff returns. Recommendation recovery now collects a fresh evidence
batch and always runs the second candidate-and-audit pass. An explicit budget
may be verified from an independent reviewed price or official MSRP/list price
without being described as a live checkout quote. If no candidate passes, the
reply lists the rejected candidates and evidence gaps; reading sources remain
clearly labeled leads rather than replacing the requested recommendation.

Markdown Evidence V1.10.40 renders every user and Bekki chat bubble through a
bounded safe-Markdown layer while retaining JSON as the model/runtime
transport. Search evidence is no longer displayed as detached link badges.
Each ordinary search source, recommendation candidate, news result, product,
place, or social post is one ordered block: its own Markdown context, its own
image (or an explicit unavailable-image placeholder), then its matching HTTPS
link. Duplicate source URLs already represented by a richer result card are
removed. Recommendation metadata, requirement matches, supporting facts, and
pros/cons stay attached to the relevant candidate. Existing chat history is
upgraded in place because plain text remains valid Markdown. The V1.10.39
social media limits remain unchanged: Xiaohongshu may show three original
post images plus one body-text capture, while Reddit shows one post-body
capture. The local model, 8192-token context, persistent minimized Edge
profile, and 16 GB GPU operating target are unchanged.

Social Evidence Package V1.10.39 makes the displayed evidence match each
platform. An opened Xiaohongshu post can show its first three original post
images in order plus one complete body-text capture; an opened Reddit post
shows exactly one post-body capture. Each card links directly to the original
post, while a small search-card crop is retained only as an explicitly labeled
fallback when the post cannot be opened. The local 12B model sees at most two
images per call; a four-asset Xiaohongshu post uses two bounded visual passes,
and two Reddit text posts share one text-only pass. Reddit searches preserve
problem/limitation intent, rank DISCUSSION requests by visible comment counts,
and scope conclusions to the verified sample. Price Top-N requests use PRICE
rather than popularity; contextual values such as `330💼`, `250`, `190`, and
`1.9k` remain prices with unknown currency unless a unit is visibly shown.
Bilibili now requires a native search response or a real image-bearing video
card, so its footer BV link cannot suppress the single first-load refresh.
The persistent minimized Edge profile, `gemma4:12b`, and `num_ctx=8192` remain
unchanged for practical use alongside a foreground game.

Social Evidence UI V1.10.38 keeps Bekki's local 12B model and 8192-token
context while making social results visibly auditable. Up to two title-bound
post or search-card screenshots are cached locally and displayed beneath the
reply; clicking an image opens the cached evidence. Search-only cards are
clearly labeled and cannot invent a missing restaurant, seller, or product
identity. Price-like values in an obvious listing, menu, or card-price chart
remain usable even without a shown currency (`250`, `190`, `1.9k`, `15🍞`),
with the currency reported as unknown and asking/displayed prices kept
separate from completed sales. Reddit requests are adapted to platform-native
search language, explicit “most discussed” requests sort by comments within
the requested time window, and aggregate claims need at least three opened
posts. Fast CDP screenshot fallback avoids the prior 30-second font wait, and
generic Rednote shells or Reddit login artwork cannot become post evidence.

Social Comprehension V1.10.37 replaces the restaurant-shaped social detail
schema with universal post understanding. Each selected post is isolated in
its own bounded multimodal call and receives up to two title-bound views: a
dominant-media crop and a wider page frame. Text findings require exact visible
quotes; image findings remain calibrated pixel observations. The detail model
no longer guesses engagement metrics. A separate bounded synthesis compares
posts to answer the user's actual task, detects location, currency, identity,
unit, and price-binding conflicts, and refuses an unsupported Top-N result.
Malformed vision JSON retries once as text-only without retaining image claims.
Reddit compact relative dates and explicit subreddit scope are enforced. The
shared Edge window stays minimized during automation and no longer receives a
bring-to-front command; interactive login uses the same persistent profile and
saved website session. The model remains gemma4:12b with an 8192 context.

Social Context Budget V1.10.36 fixes the case where successful Bilibili
research opened five real post pages but the optional introduction pass sent
8519 prompt tokens into an 8192-token model context, causing all completed
evidence and cards to be discarded. The model context remains at 8192 to
preserve practical 16 GB GPU headroom for a foreground game. Each introduction
batch now contains at most two posts, 500 characters of search-card text and
1300 characters of opened-page text per post, and a 1200-token output budget.
One failed enrichment batch is skipped without discarding grounded titles,
authors, dates, interaction counts, links, images, the direct reply, or cards.
The controller also has a final evidence-only fallback for unexpected
introduction errors. No new model, search provider, AI role, or arbitration
gate was added.

Bilibili First-Load Retry V1.10.35 fixes the observed case where Bilibili's
first search navigation showed an empty result area but one manual refresh
rendered the results. Before accepting any Bilibili page snapshot, Bekki now
checks both native response candidates and rendered cards. If both are empty,
it reloads that same tab exactly once, reattaches the native-response listener,
waits for the result grid, and samples only the post-reload page. A successful
first load is never reloaded, and a persistently empty page is not placed in an
unbounded retry loop. New Bekki Edge launches also suppress Edge's translation
prompt; an already-running Bekki Edge receives that flag after it is closed and
started again. No new search provider, AI role, or arbitration gate was added.

Unified Browser V1.10.34 replaces Bekki's separate social browser, Casper
research browser, and temporary rendered-page fallback with one persistent
normal Microsoft Edge session. All web search, news, recommendations, product
pages, downloads, and social research now use port 9225 and one isolated Bekki
profile. It starts minimized, shares cookies and login state across Bekki web
tasks, and is shown only for a user handoff. A task closes only the tabs it
opened and never restarts the shared browser. The retired 9223 and 9224 Bekki
sessions are cleaned once by exact legacy port and profile markers; personal
Edge sessions are not targeted. No new AI role or arbitration gate was added.

Bilibili Native Response V1.10.33 addresses the remaining case where a real
Edge user agent still received only Bilibili's navigation shell. Bilibili
searches now use Bekki's dedicated normal Edge process in minimized mode. The
same page pass also captures successful structured search responses issued by
that Bilibili page, converts only bounded public video rows into grounded
candidates, and then opens each selected real video page through the existing
detail reader. Non-success responses, risk-control replies, login, consent,
CAPTCHA, and other platform controls remain fail-closed. No third-party search
service, direct API credential, new AI role, or arbitration gate was added.

Bilibili Render Recovery V1.10.32 fixes the case where Bilibili returned its
compatibility/navigation shell to Bekki's managed headless Edge instead of the
real result grid. Before navigation, the Bilibili tab now reports the actual
connected Microsoft Edge version in a normal Windows Edge user agent and uses
Chinese-first browser language preferences. The DOM reader also follows
bounded open shadow roots and infers a card only from a compact image-bearing
ancestor. A lone legacy `/video/` link in page chrome is rejected rather than
being presented as search evidence. Existing login, consent, CAPTCHA, and
platform access controls remain fail-closed; no new AI role or arbitration
gate was added.

Bilibili Card-First DOM V1.10.31 fixes the remaining case where two generic
profile/navigation links survived but the much larger visible video result
list did not. The same browser pass now selects all `/video/` and
`/bangumi/play/` links before scanning ordinary anchors, recognizes Bilibili's
current card containers, reads up to 12 same-page frames, and keeps real video
cards ahead of generic profile links. A bounded seven-second result wait
allows the SPA list to attach before capture. Diagnostic logs now report total
anchors, video links, video cards, frame count, and three candidate samples,
so a future platform-loading failure can be distinguished from a parser
failure. No new AI role or arbitration gate was added.

Bilibili Visible Results V1.10.30 fixes a rendered Bilibili search page being
reported as empty when generic page text contained only navigation and footer
content. The existing browser reader now scans a bounded larger anchor set,
merges duplicate links, recognizes visible Bilibili result-card containers,
and places their literal text before generic page chrome in the existing
Social Evidence call. This preserves titles, authors, dates, and visible
interaction labels that were already present on the loaded page. Bilibili
thumbnail URLs ending in a transformed `.jpg@...avif` suffix are normalized to
the same source image's original JPEG URL so Qt can render both new and
previously stored result cards. No screenshot supplied by the user becomes
runtime evidence, and no new AI role, semantic classifier, or arbitration gate
was added.

Social Relevance Scope V1.10.29 makes the existing Social Query AI choose both
the source-language query and its evidence scope in one call. If the user does
not request a time window, Bekki searches and ranks by semantic relevance to
the complete question; old or undated posts are not removed merely for age,
and visible interaction is only a secondary signal. RECENT mode and its strict
date validation remain available only for explicit freshness requests such as
"最近一周". The same scope controls the platform's native sort, evidence
selection, post summaries, cards, and direct reply. Replies use the actual
requested platform name instead of assuming Xiaohongshu. No new AI role,
semantic Python classifier, or arbitration gate was added.

Bilibili and Reddit Social Search V1.10.28 extends the existing MAGI,
Melchior, and Casper social-search path to Bilibili and Reddit. It opens each
platform's native search page in Bekki's existing managed Edge profile,
preserves source-language names, aliases, slang, UIDs, BV/AV identifiers, and
subreddit expressions in the AI-built query, and accepts only bounded public
content/profile URLs from the requested platform. Reddit text posts no longer
need an image to become evidence, while the existing image-first filtering for
Xiaohongshu and Instagram remains unchanged. No AI role, semantic Python
classifier, or arbitration gate was added. Login, consent, CAPTCHA, and other
platform protections remain user-controlled and fail closed when the page
cannot be read.

Screenshot Multipass OCR V1.10.27 gives the existing local OCR adapter three
geometric readings of a short panoramic UI screenshot: full, enlarged left,
and enlarged right. The existing Gemma Vision call compares all three literal
transcriptions with the two pixel tiles, while the final image answer retains
the raw observations instead of receiving only a compressed paraphrase. The
visible-text packet grows from 12 to 24 entries so bottom engagement rows are
not mechanically dropped. Disputed characters and bare numbers must remain
uncertain unless the image establishes their exact reading or metric label.
No AI role or semantic gate was added.

Screenshot Current Evidence V1.10.26 fixes a current screenshot being read by
Vision and then replaced by text recalled from an older screenshot during the
final response. IMAGE and DOCUMENT remain current-turn evidence profiles even
if the router inconsistently labels the turn COMPANION; the conflicting
emotional flag is dropped, Balthasar and old screenshot history stay out of an
image explanation, and the current image evidence is placed last as an
authoritative final-answer anchor. The local Windows OCR adapter also uses the
correct WinRT awaiter and random-access stream result type and exposes its
failure stage, exception type, and HRESULT for Windows-side diagnosis. No new
AI role or semantic gate was added.

Screenshot OCR Fusion V1.10.25 adds local Windows OCR to the same existing
Gemma vision call and enlarges small panoramic screenshots as two overlapping
detail tiles. OCR supplies fallible source-language text evidence only; it is
not another semantic role or routing gate. Gemma must compare OCR with visible
pixels, preserve Chinese and other source scripts, and mark unresolved text as
uncertain instead of translating or completing it. If OCR is unavailable, the
enlarged Gemma path continues safely. Clear printed UI screenshot key fields
use a 90% acceptance target, not a universal guarantee for degraded images.

Screenshot Local Route Contract V1.10.24 separates attached visual evidence
from recalled Knowledge sufficiency. An image can fully support a local
explanation while `local_knowledge_sufficiency` remains `NONE` when no
Knowledge candidates were recalled. If MAGI labels that auxiliary field
`SUFFICIENT` or `PARTIAL` with an empty candidate packet, the runtime now
normalizes only the impossible field to `NONE` and preserves MAGI's valid lane
instead of discarding the route and calling a recovery model. Screenshot bytes
remain local and no new AI role or routing gate was added.

Completed Historical Milestone Knowledge V1.10.23.2 makes the existing time
scope and lifecycle AIs recognize a request to discover the date or year of a
named completed milestone as history rather than current state. Public debut,
founding, first-release, first-appointment, and similar one-time facts use
`EXPLICIT_PERIOD`; when the accepted evidence supports the exact period, the
existing partitioner and lifecycle auditor may store the atomic claim as
`FIXED_HISTORY`. Upstream `CURRENT_ACTIVE_STATE` retrieval metadata can no
longer override a visibly completed historical claim. No new AI role or
synchronous answer gate was added.

Curiosity Foundation Draft Calibration V1.10.23.1 strengthens the existing
Writer without adding another AI role or retry gate. A safe FOUNDATION turn
about an identified public subject now produces a distinct approachable
question when an uncovered facet remains. Narrow history such as a formal-unit
list, an organizational-term definition, and a dated roster no longer causes
the Writer to return `proposal:null` merely because it does not already know a
specific performance, person, or story. Asking for such an example is an open
question, not an unsupported factual assertion. Privacy, duplicate, breadth,
and specialist-depth checks remain unchanged.

Curiosity Native Knowledge and Idle Exploration V1.10.23 connects a verified
Curiosity result back to the existing Curiosity Writer during later idle
passes. Bekki can therefore learn a representative Team SII performance and,
without waiting for another user question, form one proportionate next
question about a distinct approachable facet. Each generated draft records
its exact source Curiosity and Knowledge IDs. Unverified answers, expired
current states, and local-model guesses cannot seed this loop. Selection,
privacy, duplicate, and gradual-depth rules remain unchanged. The legacy
three-question default migrates to a bounded ten questions per local day for
this test cycle.

Curiosity Knowledge intake now accepts three reusable lifecycle shapes through
the existing Candidate and Verdict roles: durable explanations, reviewable
maintained structures, and exact fixed historical snapshots. Current people
rosters, current affiliations, schedules, events, and news remain journal-only.
Newly verified Curiosity knowledge reopens the Daily Curator later on the same
day, while expired reviewable knowledge can be renewed only by fresh verified
evidence.

Daily Curator also creates a presentation-only native-name form without
rewriting the authoritative claim. Chinese public names are preferably shown
in Chinese, Japanese public names in Japanese, and source/romanized spellings
remain aliases. If a conversion is uncertain, the original spelling is kept.
The preferred form participates in retrieval and final replies, but cannot
change facts, dates, membership, or entity scope. These changes strengthen the
existing Writer, Candidate/Verdict, and Curator; no AI role or synchronous
reply-path gate was added.

Historical Snapshot Lifecycle Calibration V1.10.22.1 removes a contradictory
instruction between the existing lifecycle auditor's prompt and JSON schema.
The first partitioner's `persist=false` is advisory: when an exact people
roster is visibly anchored to a completed past snapshot, carries the same
source-supported closed period in temporal metadata, and passes the existing
non-semantic safety contract, the lifecycle auditor may and must correct it to
FIXED_HISTORY, stable, and persist=true. Future personnel changes cannot alter
who was on a team at that recorded time.

Current or open-ended people rosters remain changing and never enter
Knowledge. The change strengthens the two existing AI roles and supplies the
host-local date as temporal context; it adds no third AI, extra factual gate,
Python semantic classifier, or synchronous delay.

Knowledge Intake V1.10.22 lets an ordinary low-risk FACT_LOOKUP that already
passed Casper's 3-5-7 evidence process contribute reusable claims to
Knowledge. Capture runs after the user reply on NERV's existing background
writer, so it cannot delay, replace, reject, or rewrite the accepted answer.
The existing partitioner and lifecycle auditor decide claim-by-claim whether
anything is reusable; no additional AI role or factual gate was added.

A maintained formal unit set may remain stable or reviewable, while current
people rosters and current personal affiliations remain current-turn-only. A
completed historical people roster may enter Knowledge only as FIXED_HISTORY
and only when Casper's accepted temporal validation supplies an exact closed
snapshot or season. That exact source-supported period is required in both the
claim and temporal identity; broad user wording such as "2025" cannot create a
generic annual roster from a November snapshot.

Curiosity Breadth V1.10.22 distinguishes a genuinely different foundation
facet from another detail in the same list or roster. After a FOUNDATION
roster, affiliation, list, or organizational-definition turn in a new or
developing topic, the existing Writer must move to an approachable facet such
as people, history, works, performances, events, stories, relationships,
culture, or ordinary behavior. Asking which member is newest, what role each
member currently has, or another status column remains the same narrow facet.
The existing Selector re-reads the literal question; no new model call or
Python domain classifier was introduced.

Curiosity Foundation Calibration V1.10.21 prevents a narrow cluster of prior
questions from masquerading as broad topic maturity. Drafted, merely asked,
or unverified Curiosity does not establish learned coverage, and several
organization-list facts remain one narrow lane rather than several foundation
facets. After a FOUNDATION user turn, both NEW_OR_SPARSE and DEVELOPING topics
must continue with a concrete FOUNDATION question. Question depth follows its
hardest requested lens, so a comparison about brand positioning, audience
segmentation, promotion strategy, contracts, governance, or professional
operations remains SPECIALIST. The existing Writer and Selector enforce this
progression; no additional AI role, gate, model call, or Python keyword
classifier was added.

Knowledge Breadth V1.10.20 keeps early curiosity close to what the user has
actually explored. The existing Curiosity Writer receives bounded active
Knowledge and recent curiosity history, declares the topic's maturity and the
proposed question's depth, and begins a new or sparse topic with approachable
people, history, works, events, stories, relationships, culture, or ordinary
behavior. Specialist contracts, governance, strategy, or methodology are
proportionate only when the user's current turn is already specialist or the
related record history genuinely supports that depth. No new AI gate or model
call was added; Python validates declared IDs and lifecycle shape but does not
choose a topic or interpret domain keywords.

Historical Snapshot Knowledge V1.10.20 records a people roster tied to an
exact completed date or closed season as FIXED_HISTORY. Its closed period is
part of the knowledge identity, so 2024 and 2025 snapshots remain distinct and
the daily curator cannot merge them merely because they share an entity. MAGI
may use a snapshot only for the exact same historical period. An active or
current people roster always routes SEARCH and remains current-turn-only,
while the maintained list of formal organizational units keeps its existing
stable/reviewable behavior. No new AI gate or model call was added.

Knowledge-Aware Routing V1.10.19 recalls active Knowledge before MAGI instead
of after MAGI and Melchior have already selected SEARCH. The same existing
MAGI call now judges exact entity, relation, time-scope, and facet sufficiency.
When the recalled claim completely answers the request, MAGI selects LOCAL and
Melchior directly honors that decision; partial or mismatched Knowledge still
uses SEARCH. The recalled candidates are reused by the final answer and no new
AI gate or model call was added.

Adjacent Curiosity V1.10.19 gives the existing Writer bounded question history
and a gradual depth policy. A newly encountered topic begins with accessible,
topic-adjacent context; specialist contracts, governance, business mechanics,
or technical mechanisms follow only when the user or related history shows
that depth. Python does not classify the topic or choose the question.

Audit Finding Normalization V1.10.18 removes the Answer Auditor's duplicate
global verdict from the model output. The same single model call now supplies
only semantic findings and a canonical answer extracted from the candidate;
the runtime maps those findings consistently to AUTO_VERIFY or REJECT without
interpreting facts, entities, or domain keywords. Consequently, a complete
core can no longer be rejected after the model has already marked it direct,
complete, policy-compliant, conflict-free, and confidently extractable.

The canonical answer is now mandatory for both clean and cleaned candidates.
When the candidate includes a removable false event or justification, only
that addition is omitted; the retained answer is what Bekki returns and stores.
No new AI role, gate, external request, keyword classifier, or model call was
added.

Core Claim Isolation V1.10.17 prevents the existing Answer Auditor from using
its latent model knowledge as undeclared negative evidence. In this fallback
stage, a belief that a retained claim is unfamiliar, nonstandard, or not
independently verifiable cannot override the selected low-impact External-AI
policy. Missing web corroboration is expected after bounded research and is
not itself a conflict.

The same auditor now separates each candidate assertion into required core,
necessary qualification, or removable addition. A false adjacent event or
source justification does not globally contaminate a complete core answer;
only a direct contradiction affecting the retained core or a contradiction in
the supplied bounded web evidence may reject it. No AI role, gate, arbiter,
external request, keyword classifier, domain-specific rule, or model call was
added.

Audited Core Answer V1.10.16 prevents a complete low-impact fact answer from
being discarded merely because the External-AI response also contains
removable, unreliable justification. The existing Answer Auditor now chooses
between using the candidate as-is, returning a complete canonical core made
only from facts explicitly present in the candidate, or rejecting the answer.
Only the audited answer is shown and stored; Python does not select, add, or
correct facts.

The auditor now receives Bekki's host-local current date as authoritative
temporal context and repeats it in the final scope anchor. This prevents the
model's assumed present date from turning a runtime-current date into a
supposed future date. High-impact answers still require their existing second
certification, current-turn facts still do not enter Knowledge, and incomplete
or conflicting cores still fail closed. No AI role, gate, arbiter, external
request, keyword classifier, or domain-specific rule was added.

Answer Audit Scope Anchor V1.10.15 fixes a post-fallback scope drift in which
the Answer Auditor could replace a request for formal organizational units
with an adjacent search page's member-list topic. The exact user request and
candidate External-AI answer are now the binding audit pair, and the request
is repeated in a final scope anchor after all optional evidence.

Bounded web results are reduced to at most six compact conflict excerpts and
are explicitly subordinate to the audit pair. Page bodies, search-generated
facets, prior certification prompts, and prior candidate answers no longer
inflate or redefine the final audit. This keeps the audit packet below the
model's normal byte budget for ordinary fact answers and prevents middle
truncation from hiding the question-answer relationship. No AI role, gate,
arbiter, external request, keyword classifier, or domain-specific rule was
added.

Nonstructural Lifecycle Boundary V1.10.14 prevents the retrieval word
`current` from collapsing reusable formal structures into current-turn-only
facts. The standalone fallback lifecycle vocabulary now names its transient
branch `TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT`: current affiliations, people
rosters, schedules, prices, scores, versions, availability, and events remain
transient, while a current complete set of formal teams, departments,
provisions, or other maintained units remains reusable structure.

The authoritative user question is now isolated from browser-generated entity
facets before lifecycle judgment. Casper's time scope remains available only
as non-authoritative freshness metadata. The existing independent auditor sees
the first Governor's sharing preview but not its lifecycle label, interval, or
reason, so it makes a genuinely independent lifecycle decision. This release
adds no AI role, gate, arbiter, keyword classifier, or model call.

Fallback Lifecycle Basis V1.10.13 applies the same explicit semantic-basis
contract to standalone External-AI fallback questions that V1.10.12 already
used for mixed-answer claim partitions. The existing Governor and independent
policy auditor now choose `lifecycle_basis` before `knowledge_type`. A present
complete list of formal organizational units is
`MAINTAINED_SET_OR_STRUCTURE` even when the request says `current` or `目前`;
people rosters, one person's current affiliation, schedules, prices, scores,
versions, and events remain `TRANSIENT_CURRENT_STATE_OR_EVENT`.

This release adds no AI role, gate, arbiter, or model call. Python validates
only the internal consistency of the AI-selected basis, lifecycle label, and
review interval. A low-impact stable or reviewable fallback that enters
Knowledge retains the selected basis for future lifecycle review. The
authoritative user request also prevents an upstream fact-scope summary from
silently broadening a formal-unit question into member assignments or per-unit
operating status.

Structure Lifecycle Authority V1.10.12 fixes mixed answers in which a current
complete list of formal organizational units was incorrectly treated as a
people roster and therefore withheld from Knowledge. The existing partitioner
and lifecycle auditor now explicitly distinguish maintained official units
from the people assigned to them. The word `currently` or an as-of date does
not by itself make a canonical unit set current-turn-only.

The existing lifecycle auditor is now the final semantic persistence judge.
The partitioner's `persist` field is advisory rather than an irreversible
veto, so the auditor can correct an eligible formal unit set to stable or
reviewable without another AI call. Python still fails closed unless the exact
claim is low impact, directly supported by the answer, free of known evidence
conflict, sufficiently confident, and structurally complete. Current people,
individual affiliations, lineups, and schedules remain changing and cannot be
persisted. Lifecycle audit V7 rechecks older mixed claims without rewriting
their text.

Language-Safe Knowledge Review V1.10.11 makes translation preservation
language-neutral. For ordinary fact research, an expression without a safe
exact equivalent stays verbatim and may appear inside a mixed-language query;
the rest of the query can still be translated. This does not skip bounded
3-5-7 research or invoke External AI early. For social search, all meaningful
user search expressions stay in their original form on every platform; only
the command/platform wrapper and redundant wording may be removed. Python
validates the AI contract but contains no language, platform-vocabulary, or
domain keyword map.

The single mixed-claim lifecycle auditor now treats a maintained official set
or structure as either `stable` or `reviewable`, according to its own semantic
judgment. A stable record has no fixed expiry but is eligible for randomized
idle review; maintained structures receive higher sampling weight than fixed
history or durable mechanisms. At most one eligible stable record is checked
per idle local day through the existing bounded 3-5-7 search. Supporting
evidence records a review without rewriting the claim. Insufficient evidence
leaves it unchanged. Strong contradictory evidence quarantines it as disputed,
but never silently creates a replacement. Current personal affiliations and
other transient states remain current-turn-only. The former final lifecycle
critic has been removed, so valid decisions use one lifecycle AI and a retry
only for malformed or internally inconsistent output.

Semantic Grounding V1.10.10 introduced the source-expression and entity
contracts that V1.10.11 generalizes. It strengthened the existing AI contracts without
adding an AI role, gate, arbiter, or normal-path model call. Entity Scope now
marks a source expression as either user-established or still an open research
target. If its exact translation is uncertain—or its meaning or contrast is
the question itself—the search query keeps the original expression verbatim;
mixed-language search is valid and no guessed gloss may pre-answer it.

The existing mixed-claim lifecycle AI now selects an explicit semantic basis
before its lifecycle label. Fixed history and durable definitions or mechanisms
map to `stable`; maintained official sets and structures map to `reviewable`;
current states, affiliations, and events remain current-turn-only. Python only
checks consistency between those AI-selected fields and never classifies a
domain or keyword. Lifecycle audit V5 re-audits older mixed claims but does not
silently update facts; expiration only ends freshness, and user correction can
invalidate a claim earlier.

The existing Daily Curator output now grounds every subject in the literal
claim, records the selected entity ID and rejected adjacent hierarchy IDs, and
attaches claim-language evidence to every relationship. Related entities still
share one broad ecosystem JSON, while a local entity, umbrella organization,
internal unit, and person retain distinct identities.

Source Taxonomy & Knowledge Lifecycle V1.10.9 keeps the same query AI roles
and model-call budget. The existing search-query writer, Entity Scope planner,
auditor, and certifier now preserve source-language taxonomy whose meaning or
contrast is itself being researched; a draft gloss cannot redefine that term
merely by placing the original expression in parentheses. The lifecycle V4
contracts keep maintained official unit sets as persisted `reviewable`
knowledge with a proportionate freshness deadline, while individual current
affiliations remain current-turn-only and fixed personal history is evaluated
separately. Review deadlines expire freshness and never silently auto-update a
claim; user disputes can invalidate it earlier. Existing V3 mixed claims are
eligible for idle re-audit. The existing Daily Curator contract now requires
distinct hierarchy-level entity IDs and semantically consistent relations, so
an internal unit cannot be relabeled as its parent's sister organization.

Focused Certifier Calibration V1.10.8 applies the same scope-intent standard
to focused follow-up certification without adding an AI gate or model call. An
exact entity name remains that entity unless the literal query broadens it. A
precise positive taxonomy, such as a joining cohort/batch plus its distinctive
source-language term, may distinguish a neighboring trainee or membership
status without enumerating every negative exclusion. Focused translation is
judged independently from hierarchy. Fixed rejection/rewriting examples were
removed from all focused prompts, while their supplied JSON schemas continue
to enforce structure.

Query Certifier Calibration V1.10.7 strengthens the existing query auditor and
adversarial certifier without adding another AI gate or model call. The
certifier now judges whether the literal query clearly communicates its scope;
it may not demand a guarantee that every search result will be perfectly
filtered. Explicit “entity itself/core entity only” or adjacent-scope exclusion
wording is a valid hierarchy boundary, including when parenthetical. The old
prefilled `accepted:false` JSON example was removed so it cannot anchor every
certification toward rejection. Translation is judged independently from
entity hierarchy. The source tests also prohibit adding a third query-scope
arbiter.

Focused Query Set V1.10.6 separates primary-query certification from focused
follow-up certification. A focused query now has a dedicated AI contract that
names its assigned missing facet, confirms that any rewrite preserves that
same facet, and separately judges whether the approved candidate plus its
labeled sibling queries collectively cover the evidence gaps. A focused query
is no longer rejected for omitting facets assigned to siblings, and an auditor
cannot silently replace it with a sibling's facet. Python labels query slots
and validates the AI contracts but contains no entity, taxonomy, or language
classification rule.

Recycle Action Arbiter V1.10.5 prevents an old chat from turning a current
“open the Recycle Bin” request into an item-restore workflow. The broad recycle
planner and focused restore-intent AI now judge the current request
independently. If they disagree, a third AI receives the current request first
and arbitrates the requested outcome. Old conversation is reference-resolution
material only. Invalid arbitration fails closed to clarification, never to a
restore or item selector. Python validates only the closed action contracts; it
does not infer Chinese or English recycle intent from keywords.

Knowledge Correction V1.10.4 retains the bounded Gemma 4 migration:
`gemma4:12b` owns primary conversation, MAGI, research, vision,
verification, learning, and final writing; `gemma4:e4b` owns fast routing,
profile writing, objective-fact auditing, and bounded launcher vision.
`llama3.2:latest` remains limited to small closed decisions. Ollama receives
prompt instructions through its native system field. Gemma 4 thinking is
strictly normalized to a Boolean: the existing `low` quick path stays off,
while only explicit `high`, `on`, or `True` enables thinking. Context remains
capped at 8K for 12B and 4K for E4B to protect the RTX 5080 16GB stability
envelope. Models larger than 12B are still remapped to 12B.

When the user says a previous answer is wrong, one local AI now distinguishes
user-authoritative personal corrections from externally checkable public
facts. Personal identity, family, household, device, routine, account, and
preference corrections stay local. For a public objective dispute, only the
exact AI-selected Knowledge records are marked `disputed` and excluded from
recall while Bekki re-runs official-first FACT_LOOKUP. The user's assertion is
a reason to investigate, never evidence that the replacement is true. A
verified reusable replacement supersedes the old record; a same-ID refresh
reactivates it; an inconclusive search leaves it inactive. Every change keeps a
bounded `revision_history` instead of erasing the previous claim.

Every lifecycle result that would make any mixed-answer claim permanently
`stable` now passes through a final independent Gemma 4 durability critic,
even when the partitioner and first auditor agreed. The critic applies a
future-change counterfactual across the complete claim set: maintained official
unit inventories remain reusable but become `reviewable`, durable definitions
and mechanisms may stay `stable`, and current people, rosters, affiliations,
schedules, prices, and events remain current-turn-only. Python triggers and
validates the structured review but contains no entity or domain classification
table. V2 mixed records are automatically eligible for this V3 re-audit.

When FACT_LOOKUP exhausts bounded 3-5-7 research without one complete answer,
Bekki may ask ChatGPT Desktop using only the current public question. Local AI
assigns one of four lifecycles: permanent stable knowledge, periodically
reviewable knowledge, current-turn-only facts, or high-impact facts requiring
a second certification. A second independent local AI audits every reusable
claim after mixed-answer partitioning and chooses any review interval from the
fact's likely change rate and stale-answer cost; the schema maximum is not a
default. A non-proportional decision or lifecycle disagreement is sent to a
third independent AI arbiter. Stable and
reviewable low-impact answers enter
Knowledge; reviewable entries expire on their AI-selected recheck date.
Current person/team/status facts answer the present turn but are never stored.
High-impact legal, medical, financial, safety, or reputational answers require
a second certification and are not automatically stored. Credentials and
sensitive private data are never sent.

Every newly approved stable or reviewable fact first enters the auditable
`data/knowledge/inbox.json` queue. At the first idle opportunity once per local
day, a Gemma 4 curator assigns each record to a broad knowledge ecosystem.
V1.10.4 processes at most three structurally rich assignments per model output
and commits each completed batch independently, preventing an existing backlog
from truncating the whole daily JSON plan. The curator still selects
distinct entities and relations, a facet, aliases, and retrieval keywords.
Related organizations, members, people, and sister organizations can share one
topic file such as `data/knowledge/topics/snh48.json` without being treated as
the same entity. `data/knowledge/index.json` maps aliases and keywords back to
those topic documents. Duplicate claims are linked; contradictions are moved
to `data/knowledge/conflicts.json` and excluded from recall. Python validates
IDs, completeness, and write safety but contains no domain-specific topic map.
Mixed-answer claims written before the current audit version are automatically
re-audited during idle curation. This includes V1 audit records mistakenly
demoted to expired/current-only. Lifecycle corrections update the authoritative
record and requeue its topic copy without clearing user data.

For a mixed request, an independent AI may separate reusable structure from
current-turn-only details after the external answer arrives. Only atomic
stable/reviewable claims can enter the inbox. Current members, affiliations,
rosters, schedules, events, prices, and news still answer only the present
turn. A failed classification or invalid JSON leaves the record pending and
does not alter its verification state.

Before FACT_LOOKUP searches, one local AI now derives a binding semantic
Entity Scope from the original user message. A separate local AI audits the
generated search query and every follow-up query against that scope, rewriting
translation or hierarchy drift before browser discovery. Distinctive
source-language taxonomy is retained when a safe exact translation is
uncertain, so an institutional cohort term cannot silently become a training
status. Focused follow-up queries may each cover one missing facet when their
AI-supplied query set collectively covers the remaining gaps; they are no
longer rejected for failing to repeat the entire original request. The Python
runtime checks only the structured AI contracts; it contains no SNH48,
team-name, or
`group` keyword rule. A further independent AI now attacks rather than merely
approves the literal query: it must construct the strongest excluded-scope
interpretation using only the text the search engine will see. If that reading
remains plausible, the query is repaired once and challenged again. A final
independent AI also rejects answers about an
adjacent parent, affiliate, sibling, internal unit, category, or historical
entity. Missing or wrong-scope evidence can no longer be presented as proof
that the requested fact is not yet available; it falls through to the governed
External-AI policy instead.

Install the new local weights before starting this build:

```powershell
ollama pull gemma4:12b
ollama pull gemma4:e4b
ollama pull llama3.2:latest
```

Objective Fact Verification V1.8 prevents an ungrounded LOCAL draft from
becoming its own evidence. A cheap fact-heavy prefilter preserves the fast path
for greetings, companionship, writing, translation, math, and personal facts.
When a local answer asserts concrete public-person, organization, team, roster,
status, version, or date details, a compact semantic audit runs before display.
A VERIFY result automatically reroutes the request through Casper's existing
official-first FACT_LOOKUP. If no audited answer is available, Bekki withholds
the local draft instead of guessing. A user's “好像不对” triggers independent
verification but is not itself treated as proof. Current rosters and similar
changing facts are verified when asked and are not frozen into durable stable
Knowledge.

Curiosity treats every raw LOCAL reply as UNVERIFIED_ASSISTANT_OUTPUT and does
not receive its text. This blocks hallucinated names or lists from being copied
into the next ChatGPT Desktop question. Evidence-backed research replies remain
available to Curiosity under an explicit grounding label.

NERV Curiosity Soft Gate V1.7 no longer treats the writer model's uncalibrated
interest and confidence scores as normal hard rejection thresholds. Safe,
well-formed questions with moderate scores proceed to the independent Selector,
which owns the useful-question judgment. Only confidence below 0.40 is rejected
before selection. Privacy, language, malformed-contract, and duplicate gates
remain deterministic, and the runtime log now reports the exact dismissal
reason.

External AI Answer Anchor V1.6/V1.10.4 prevents an older off-screen ChatGPT response
from being mistaken for the answer to a newly sent NERV question. Bekki records
the full UI Automation conversation tree before sending, waits until the exact
outbound user prompt appears in document order, and accepts only assistant text
after that prompt. When a new Copy response control appears, Bekki asks UIA to
scroll that exact control into view before reading it. V1.10.4 identifies the
new control by its UIA runtime identity even when WebView virtualization keeps
the total Copy-control count unchanged, and tolerates only cosmetic UIA line
wrapping in the exact prompt anchor. If the current prompt
anchor never appears, the adapter fails closed instead of returning an older
answer.

Knowledge Clusters V1.5 separates curiosity from durable memory. NERV may ask
about stable background knowledge or useful current snapshots, but only stable,
reusable facts can enter Knowledge. Fast-changing rosters, trades, injuries,
prices, schedules, policies, software versions, events, and news stay outside
long-term Knowledge. The AI assigns a semantic verification tier: ordinary
stable background facts use one qualified independent source to corroborate the
external-AI answer, while medical, legal, and sufficiently technical claims use
two independent sources, consensus, and a second certification pass. Python
enforces the stable-only and medical/legal safety floors.

Verified facts are grouped by domain and reusable entity in
`data/knowledge_clusters.json`. A later related question can retrieve the local
cluster deterministically before generation, so a question such as how to
improve a company modeled on SNH48 can reuse verified SNH48 organizational
knowledge without another external-AI request or search.

News Feed Reliability V1.4 resolves "这几个月" and equivalent requests into a
bounded recent date window. A model-generated query that introduces an older
year is discarded. Rendered-page news extraction gets one smaller,
schema-constrained recovery attempt after invalid JSON. If extraction still
fails, Casper returns limited evidence and the final layer may not claim that
there was no news.

NERV Context Isolation V1.3 treats a self-contained current message as the
only routing authority. Previous conversation text is withheld from Melchior,
MAGI audit, lane recovery, and content-action routing unless the current
message contains an explicit unresolved reference such as "这个", "刚才那个",
or "the previous one". This prevents an older person or claim from replacing
the user's current subject while preserving genuine follow-up questions.

Screenshot Search V1 analyzes an explicitly attached image, full-screen
capture, active-window capture, or selected screenshot region before MAGI and
Melchior route the request. A request to explain the image stays local; a
request to verify a visible sports/news claim, look up an error, or find a
visible product can use Casper's existing evidence-backed search modes. Vision
runs once per turn. Only bounded, privacy-filtered textual evidence reaches the
search pipeline; the original screenshot is not uploaded to a search engine.

The header now includes a settings button for chat appearance. It can change
the conversation/input font family and size, replace Bekki's avatar with a
validated PNG/JPG/JPEG/WebP image, preview changes before saving, and restore
the defaults. Saved choices live in `data/ui_preferences.json`; custom avatar
files are copied into `data`, so the stable installer preserves them alongside
the user's existing memory and runtime data. Applying a setting updates visible
messages and the input area immediately without restarting Bekki.

This patch uses the installed ChatGPT Desktop app for explicitly asking
ChatGPT without an OpenAI API. Browser/CDP fallback is disabled: if the desktop
app is missing, signed out, or does not expose a safe input through Windows UI
Automation, Bekki stops without opening a web page. NERV may also select up to
ten privacy-screened curiosity questions per local day. Exact questions and external answers are recorded in
the Curiosity Journal. External answers remain hypotheses: NERV extracts at
most one low-risk factual candidate, independently searches it, and promotes
it to Knowledge only after at least two readable, independent, high-quality
sources form consensus. Insufficient, conflicting, high-risk, event, and news
claims remain outside long-term Knowledge.

Desktop V1.1 fixes the live `DESKTOP_INPUT_NOT_FOUND` result seen immediately
after application launch. Bekki now waits for the ChatGPT WebView accessibility
tree, recognizes safe composer controls exposed as Edit, Document, Custom, or
Group, and may open the official Companion Window with Alt+Space. A companion
send is allowed only after a distinct ChatGPT application window is observed;
the browser and coordinate-click routes remain disabled.

Desktop V1.2 rejects the non-editable `Composer utility bar` exposed by the
live ChatGPT Desktop build. Although its accessibility name contains
`composer`, it is only the attachment/model/voice toolbar. Excluding it lets
the request continue to the verified Companion Window fallback.

Desktop V1.3 adds an exact Windows Unicode keyboard-input fallback. When the
real message editor is focused but the clipboard is unavailable, Bekki can
type Chinese directly and then submit without browser or coordinate control.

Desktop V1.3.1 retains that proven foreground input and Enter submission, then
minimizes ChatGPT immediately and waits through background UI Automation. It
declares 64-bit-safe Windows clipboard signatures, rejects user-message labels
such as `You said:` and provider error banners as answers, and accepts only a
substantive stable assistant response. Explicit and NERV-curiosity questions
stay in the originating language; Bekki does not append an unsolicited English
translation to a Chinese question.

Desktop V1.3.2 corrects the live minimized-WebView timeout. After submitting,
Bekki restores the previously active Bekki window while ChatGPT stays open
behind it, allowing the desktop accessibility tree to continue publishing the
answer. ChatGPT is minimized only after the answer is captured. Curiosity JSON
fields are also length-bounded to prevent repetitive truncated output.

NERV Knowledge Verification V1.4 connects Curiosity to Bekki's existing Search
and Knowledge systems without making ChatGPT Bekki's brain. ChatGPT supplies a
hypothesis only. Python enforces the independent-source and consensus gates;
the local verifier writes the evidence-supported canonical claim, not the
external wording. Verified entries record all qualifying sources and retain
`external_ai_role=hypothesis_only` provenance. Journal queries show whether a
curiosity was verified, rejected, skipped, or left unverified.

V1.4 requires a candidate to answer the original curiosity directly. For a
why/cause/mechanism question, an incidental detail cannot pass the candidate
gate. One bounded recovery attempt asks for the core mechanism; if it still
returns a side fact, verification stops safely. Durable explanatory questions
are normalized to stable knowledge with no artificial 30-day expiry.

NERV adds a governed long-term cognition layer without changing the stable UI
or taking route authority from MAGI. It maintains a structured Profile Store,
an AI Profile Writer grounded only in direct user quotes, least-privilege
Context Selector, learning-event journal, audit history, and a read-only
compatibility view of Casper's verified Skills. Sensitive or low-confidence
profile proposals remain pending review. External AI receives no NERV profile
context. NERV failure cannot turn a completed request into a worker failure.
Learning V1.1 imports only Casper skills backed by a completed machine receipt
and explicit user acceptance. It stores a path-free, URL-free summary, exposes
that summary only to the final local writer, and never bypasses Casper for
execution. Rejected candidates remain unlearned, duplicate confirmations
update one record, and removed Casper skills become deprecated in NERV. An
empty learned-skill set is now passed explicitly as `[]`, so the final writer
cannot replace it with built-in model or system capabilities.

Learning V1.2 adds a reliable-model bootstrap audit for explicit requests to
learn and execute an application-specific game-content folder operation. If
the detailed router mistakes that request for a normal application action, the
12B audit may select the existing Casper content-learning workflow. Ordinary
file, system, and library operations remain outside this widening path.

Learning V1.2.1 assigns the active verified-skill confirmation boundary to the
reliable model and explicitly grounds brief confirmations such as “对了”. A
bare confirmation can no longer be reinterpreted as an application name; a
sentence that continues into a genuinely new request remains a new request.

Learning V1.2.2 prevents documentation details from broadening a learned
operation. `OPEN_DESTINATION_FOLDER` skills are described only as locating and
opening their reusable destination, even when the supporting tutorial also
mentions copying or installing content. Existing verified skills are corrected
when NERV rebuilds its sanitized compatibility view.

Learning V1.2.3 makes the current verified NERV learning view the final
authority for learned-skill answers. It is placed after Recent Conversation in
the final prompt and explicitly overrides stale assistant descriptions, so an
older incorrect copy/install claim cannot replace the current open-folder
scope. Existing skills do not need to be learned again.

Learning V1.2.4 migrates stale text already preserved in NERV's local
compatibility file. A verified `OPEN_DESTINATION_FOLDER` record is rewritten
from its authoritative scope and content type when loaded, even if Casper's
adapter is temporarily unavailable. The corrected summary and empty parameter
list are persisted without deleting or relearning the skill.

Learning V1.2.5 adds the AI-selected `NERV_LEARNING` context profile for direct
verified-skill inventory questions. Once Melchior selects this closed query
type, NERV renders the answer from structured verified fields and bypasses the
free-form final writer. Old conversation or memory can no longer expand an
open-folder skill into copying or installing content.

Learning V1.2.6 adds one reliable-model audit when the compact Melchior returns
the contradictory combination `LOCAL_ANSWER` plus a device/skill lookup signal,
or after an audited cross-lane replan ends as a local answer. The 12B model
chooses only `NERV_LEARNING` or `OTHER`, is unloaded immediately, and runs after
built-in device boundaries so ordinary Steam-library actions are unaffected.

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

Question explaining the active image or screenshot

Local Vision model

Current lookup, claim verification, or shopping request grounded in a screenshot

Local Vision evidence + Casper web search

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

ollama pull gemma4:12b
ollama pull gemma4:e4b
ollama pull llama3.2:latest

`llama3.2:latest` handles bounded compact local-action contracts.
`gemma4:12b` handles chat, learning, learned Skills, image understanding,
research, recommendation planning, candidate verification, recovery, and final
synthesis. `gemma4:e4b` handles fast routing and auditing plus the bounded
HoYoPlay screenshot check so
the launcher does not need to load the larger model merely to locate one verified
button. `gpt-oss:20b` and Gemma 3 are not required or called by V1.10.4. Set `VISION_MODEL` or
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

Screenshot text accuracy

Clear printed interface screenshots use a local two-part perception path:
Windows.Media.Ocr first supplies source-language text evidence, then the
existing single Gemma vision call checks that text against overlapping enlarged
image tiles and explains the page. OCR is not a new AI gate and never decides
the semantic route. If Windows OCR is unavailable, Bekki safely falls back to
the enlarged image tiles.

For Simplified Chinese screenshots, verify that Windows has the `zh-CN` OCR
recognizer in Windows PowerShell 5.1:

```powershell
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
[Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages |
    Select-Object LanguageTag, DisplayName
```

The 90% target applies to key fields in representative clear UI screenshots,
such as usernames, visible titles, times, and engagement counts. It is not a
universal guarantee for blurred, compressed, stylized, or occluded text.

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

Vision is single-image analysis, not continuous screen monitoring or reverse-image search

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
