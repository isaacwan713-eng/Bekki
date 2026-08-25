# Bekki R25 compact-model runtime

Build ID: `bekki-skills-v1-20260818-r25`

R25 removes `gpt-oss:20b` from every shipped runtime call. The change follows
the repeated Windows/Ollama failure:

```text
llama-server process has terminated: exit status 0xc0000409
CUDA error: shared object initialization failed
```

That failure occurred even on a 2,048-token context and a 256-token output, so
it was a model-runner/CUDA initialization failure rather than exhaustion of a
conversation token allowance.

This reissued R25 also separates the compact behavioral core from Bekki's
final-reply personality. Task planning, search, verification, safety, and tool
execution remain neutral. Facts, news, restaurants, product recommendations,
and ordinary answers receive a light virtual-idol voice only when the final
answer is written. Companion turns receive the full persona and Balthasar.

The shared lore presents Bekki as an 18-year-old virtual idol with the playful
canonical reveal that she is actually a 32-year-old former idol. Light replies
use at most one short aside or kaomoji; serious medical, legal, financial,
safety, grief, crisis, and distress topics suppress the playful style.

Fact-summary auditing and verified product recommendation synthesis reuse their
existing final 12B calls to apply the light persona. No extra styling model call
is added. Exact purchase and device-action receipts stay deterministic.

The post-acceptance R25 refresh also incorporates the live test findings:

- exact-product shopping treats an unrequested capacity, color, lid, finish,
  or bundle count as a normal variation instead of a rejection;
- official product-family collections are described honestly rather than being
  mislabeled as direct product pages;
- factual, news, recommendation, and shopping result URLs are forwarded to the
  UI source layer instead of reporting `SOURCES FOR UI 0` after evidence exists;
- news curation removes repeated cards with the same AI-created event key;
- Balthasar retries when a compact model copies pipe-separated enum placeholders
  instead of selecting one emotion, tone, and support value;
- the invalid `response_mode=COMPANION` schema echo is repaired as
  `LOCAL_ANSWER` plus `interaction_mode=COMPANION` without a second routing
  generation;
- adult, baby, child, and similar audience words are explicitly identified to
  the recommendation planner as `audience_scope=EXPLICIT`.

Exact purchase and device-action receipts remain deterministic. The purchase
receipt adds only a tiny local Bekki flourish and still uses no final model.

The final acceptance refresh adds result-level enforcement where repeated live
tests showed that prompt wording alone was insufficient:

- simple `打开 Steam`/`open Spotify` commands are forced to the one-off app
  route even if Melchior echoes `skill_route=lookup`;
- Windows launches one exact `Get-StartApps` identity through Explorer's
  `shell:AppsFolder` route, then falls back to one exact Start-menu `.lnk` for
  classic Win32 programs such as Steam; failure stops locally and never
  substitutes an unrelated open window such as Edge;
- Explorer process return codes 0 and 1 are accepted as a successful launch
  handoff, fixing the case where Steam opened but Bekki falsely reported that
  no application was found;
- an unknown application alias such as `VS Code` can be resolved by the small
  model from a bounded list of installed application names; Python validates
  the returned allowlist index, requires high confidence, and keeps AppIDs and
  paths out of the prompt;
- Melchior's ordinary router now uses `llama3.2:latest` with a 4,096-token
  context and 1,600-token output ceiling; only a failed or malformed small-model
  route escalates once to `gemma3:12b`, and the recovery path unloads the model
  that actually failed;
- `打开 HoYoPlay` learns the exact launcher identity, while `打开原神` may map
  the Chinese alias only to an explicit installed `Genshin Impact` candidate;
  a generic HoYoPlay entry alone cannot be reported as the game itself;
- after the first successful application launch handoff, Bekki atomically records the
  exact AppID/shortcut as local procedural memory in
  `data/application_skills.json`; later launches reuse the learned skill without
  adding the registry to prompts or update packages;
- explicit Steam-game commands such as `打开 Steam 里的 FM26` use their own
  bounded route. Bekki reads local Steam manifests without modifying them,
  lets the small model choose only among installed game names, validates the
  candidate index, dispatches a numeric `steam://rungameid/...` URI, and learns
  the alias for later reuse;
- `看看 Steam 库里有什么` uses a separate read-only local route that lists
  installed manifest names without exposing paths or AppIDs, browser research,
  or window-selection AI; the response is bounded to the first 100 names while
  preserving the full installed count;
- an exact target name visibly present in a listing cannot be rejected merely
  because the listing adds an unrequested capacity, lid, color, or finish;
- an AI explanation that explicitly says the user requested adult/baby/child
  use reconciles a contradictory `GENERAL_UNSPECIFIED` audience field without
  another model call;
- `yesterday` and `last night` cannot remain `CURRENT_ACTIVE_STATE` when the AI
  already named that completed relative period;
- the primary Balthasar prompt now presents valid single-value examples rather
  than a pipe-separated schema template;
- light final replies avoid duplicate bilingual text and preserve uncertain
  club/person/product names in their evidence spelling.

Packaging correction: runtime-generated `data/location.json` is deliberately
excluded from the update payload. The installer continues to protect the
user's `data` directory, and Bekki creates or refreshes that location cache at
runtime instead of installing a developer-machine copy.

Baseline migration correction: earlier cumulative projects may still contain
quoted `gpt-oss:20b` model tags in canonical root or `casper/` Python files that
were not part of the R25 payload. The installer now discovers only those two
runtime scopes, transactionally backs up every affected file, replaces the
executable tag with `gemma3:12b`, validates it, and rolls it back with the rest
of the update if tests fail. Backups, tests, virtual environments, build output,
and extracted update packages are never scanned as runtime.

When `-RunTests` is requested and Ollama is not listening, the installer starts
the installed local Ollama service and waits for readiness before launching the
few legacy contract tests that call `llama3.2:latest`. This prevents a stopped
Ollama service from appearing as seven unrelated unit-test failures.

Windows PowerShell readiness correction: the installer checks Ollama through a
bounded TCP connection to the exact IPv4 listener `127.0.0.1:11434`. It no
longer uses `Invoke-RestMethod localhost`, which could report a false negative
because of IPv6 resolution, proxy behavior, or HTTP response parsing even when
Ollama's own log showed `/api/tags` returning HTTP 200.

Installed-test correction: package-only installer tests are no longer copied
into the project test suite, where the outer downloaded installer path does not
exist. For an older `test_recycle_bin.py`, the installer transactionally updates
only the exact obsolete assertion that required `gpt-oss:20b`; negative checks
and all other test semantics remain untouched.

Router-contract correction: the cumulative R18 test now checks the current
small-model primary plus 12B recovery policy instead of requiring two 12B
router calls. This keeps `-RunTests` aligned with the runtime reduction rather
than rolling back a successful installation for an obsolete expectation.

## Runtime model contract

- `llama3.2:latest` handles short routing, confirmation, checkpoint relation,
  verification classification, and other bounded decisions.
- `gemma3:12b` handles ordinary conversation, companionship, learning,
  learned-skill selection/execution reasoning, public-web research,
  recommendations, shopping, vision, verification, and final writing.
- `gemma3:4b` handles only the bounded HoYoPlay screenshot-and-button check.
  Before it loads, Bekki unloads the compact router and waits for Ollama to
  report that its memory has been released. A failed visual-model load is
  reported separately from a genuine low-confidence visual result and is
  retried once after bounded cleanup.
- HoYoPlay capture first uses Pillow's desktop grab after restoring and focusing
  the launcher. If Windows rejects that capture, Bekki logs the actual error and
  falls back to a bounded Win32 `PrintWindow` capture of that exact launcher
  HWND. Both routes produce pixels for AI judgment; neither route chooses the
  game or button in Python.
- The final bounded click now declares every Win32 function with 64-bit-safe
  HWND and coordinate types, verifies that the exact captured HoYoPlay HWND is
  still foreground, and logs whether failure occurred during foregrounding,
  cursor movement, or dispatch. Python still does not choose the target.
- If the interactive desktop rejects `SetCursorPos`, Bekki falls back to one
  Win32 `SendInput` absolute click after rechecking the exact foreground HWND
  and virtual-screen bounds. A rejected `SendInput` reports its count and
  Windows error code; it never widens the click target.
- A high-confidence coordinate is no longer trusted by itself. Bekki draws a
  red crosshair at the proposed point and asks the compact vision model whether
  that exact marker is inside the enabled launch button. A corrected point must
  pass a second marker audit before Python may execute it.
- SendInput now separates absolute movement, button-down, and button-up with
  short bounded pauses for custom-drawn launcher controls. If the Genshin
  process is still absent after verification, the receipt is
  `game_launch_unverified`, not a completed launch claim.
- Target-audit JSON is checked for internal consistency: `target_correct=true`
  may only repeat the marked point within a small tolerance. If the same answer
  supplies materially different corrected coordinates, Bekki treats those as
  a proposed correction and requires another annotated visual audit.
- `gpt-oss:20b` is no longer required by `MODEL_REQUIREMENTS.json` and no R25
  Python runtime file contains its model tag.
- the shared `call_model` boundary converts inherited `think="low"` to
  `think=False` for Gemma 3 and Llama 3.2, preventing Ollama's
  `does not support thinking` HTTP 400 response.

## Preserved behavior

- R24's partial news-row recovery and non-empty curation fallback are included;
- R23 exact-product purchase lookup remains available;
- AI continues to own semantic selection;
- Python continues to own safety, resource, format, and execution boundaries.
- Balthasar remains limited to COMPANION turns; personality does not add a
  Balthasar call to news, facts, shopping, recommendations, or actions.

## Acceptance checks

Run these in one Bekki session:

1. `给我看看最新的曼联新闻`
2. `道奇昨天赢了吗`
3. `你今天心情怎么样`
4. `打开回收站`
5. `推荐几个 SGV 的中餐馆`
6. `推荐几个成人用的吸管杯`
7. `帮我查下怎么购买第一个`
8. `打开 VS Code` twice
9. `打开 HoYoPlay` twice
10. `打开原神` twice
11. `看看 Steam 库里有什么`
12. `打开 Steam 里的 FM26` twice (or replace FM26 with an installed game)

Expected persona log lines include `[FINAL PERSONA] LIGHT ...` for ordinary
answers and `[FINAL PERSONA] FULL ...` for the companion request. Research and
recommendation results may be playful, but their factual content must remain
identical to the verified evidence.

The log may show `gemma3:12b` and `llama3.2:latest`, but must not show a new
request using `model=gpt-oss:20b`. The build line must report R25.

The first unknown application/game alias may add one bounded small-model selection
call and should log `[CASPER INSTALLED CANDIDATE AI]`, followed by
`[CASPER APP SKILL] learned` or `[CASPER GAME SKILL] learned`. Repeating the
same request should log `reused` and skip candidate selection. Steam launch
receipts intentionally report a dispatch to Steam rather than claiming that
the game process has already finished starting.

## Installed-candidate JSON recovery

- Installed-application alias selection now constrains the compact model with a
  JSON schema and retries malformed output once with a short 12B recovery
  prompt.
- This prevents commands such as `打开原神` from turning into generated Python
  code and then failing closed before the installed candidate is chosen.

## HoYoPlay game launch workflow

- `打开原神` is now treated as a launcher workflow rather than a standalone
  Start-menu application lookup.
- Bekki first reuses the learned HoYoPlay identity, confirms that the HoYoPlay
  accessibility tree visibly contains Genshin Impact/原神, and invokes only an
  exact enabled launch button through Windows UI Automation.
- Bekki does not use fixed screen coordinates and does not click when the game
  identity cannot be confirmed. It verifies the Genshin process before claiming
  that the game opened; otherwise it reports only that launch was dispatched.
- Melchior's compact primary router now uses a JSON schema and always unloads
  the compact model before a 12B format-recovery attempt.
- Explicit `打开/启动/运行 <application>` commands are now a deterministic
  execution boundary after AI routing. Even if the router labels `打开原神` as
  LOCAL_ANSWER/COMPANION, Python forces DEVICE_ACTION, disables Balthasar, and
  runs the HoYoPlay workflow instead of letting the final persona falsely say
  that the game is starting.
- The same post-router execution boundary now covers the existing bounded
  Recycle Bin workflow. `打开回收站`, viewing its contents, and restoring a
  selected item can no longer be downgraded to LOCAL_ANSWER/COMPANION with a
  fabricated “正在打开” reply.
- HoYoPlay now falls back from an empty Windows UI Automation tree to a
  foreground-window screenshot. Gemma 3 12B must visually confirm both the
  Genshin page and an exact launch button, returns normalized coordinates under
  a JSON schema, and Python bounds-checks the point before one click. The
  compact router is unloaded first. A low-confidence or incomplete visual plan
  performs no click, and Bekki still verifies the Genshin process afterward.
