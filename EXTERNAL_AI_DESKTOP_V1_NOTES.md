# External AI Desktop V1.3.2 + NERV Knowledge Verification V1.4

## Active transport

- ChatGPT Desktop on Windows is the only active External AI transport.
- Bekki does not call the OpenAI API and does not open an External AI browser.
- The existing privacy model still prepares one exact NORMAL-risk outbound
  prompt. The proven V1.3 path focuses the real composer and submits it, then
  restores Bekki as the foreground window while ChatGPT remains readable
  behind it. ChatGPT is minimized after answer capture.

## Safety boundary

- UI Automation selects a visible ChatGPT window and an accessible message
  input; it never clicks screen coordinates.
- Bekki waits for the desktop WebView accessibility tree instead of treating
  the first visible application frame as a fully loaded composer.
- If needed, Bekki opens ChatGPT's official Companion Window with Alt+Space.
  Keyboard input without an exposed composer is permitted only after a
  distinct ChatGPT companion window has been observed and focused.
- Browser windows titled ChatGPT are rejected by executable identity.
- If a send is uncertain, Bekki stops. It does not retry automatically.
- If the prompt was sent but no answer is readable, Bekki reports a timeout
  and does not invent or resend an answer.
- `You said:`, the user's own prompt, short UI labels, and provider error bars
  such as `Request failed with status 404` cannot be accepted as an answer.
- Windows clipboard handles use explicit pointer-width signatures on 64-bit
  systems. A clipboard read failure falls back to UIA text instead of failing
  the completed send.
- Chinese questions remain Chinese. External AI governance and NERV Curiosity
  may not append an English translation unless the user explicitly asks.
- External answers remain `UNVERIFIED_EXTERNAL_AI`. NERV may use one as a
  hypothesis for an independent search, but only a separately supported
  canonical claim can enter Knowledge.
- The non-editable `Composer utility bar` is explicitly rejected as an input;
  it is a button container, not the message editor.
- If clipboard paste is unavailable after a verified editor receives focus,
  Bekki sends the exact prompt as Windows Unicode keyboard input. This keeps
  Chinese text local and still avoids browser and coordinate fallback.

## First live test

1. Install and sign in to the official ChatGPT Desktop app.
2. Install this Bekki package. The installer adds `pywinauto` to the preserved
   `.venv` when it is missing.
3. Start Bekki and ask: `帮我问 ChatGPT：为什么猫会呼噜？`
4. Expected logs include `EXTERNAL AI DESKTOP WINDOW`,
   `EXTERNAL AI DESKTOP INPUT`, and `EXTERNAL AI DESKTOP PROMPT SENT`.
   If the main window does not expose its input, expect
   `EXTERNAL AI COMPANION REQUESTED` and `EXTERNAL AI COMPANION READY`.
5. If the desktop app exposes a Copy button or stable answer text, Bekki returns
   the answer with the unverified label.

The desktop app can change its accessibility tree after an update. A missing
safe input produces `DESKTOP_INPUT_NOT_FOUND`; it does not trigger web fallback.
