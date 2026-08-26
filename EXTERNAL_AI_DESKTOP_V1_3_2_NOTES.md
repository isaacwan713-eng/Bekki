# Bekki External AI Desktop V1.3.2

This patch starts from the live-proven V1.3 transport. Bekki focuses the real
ChatGPT Desktop composer, writes the exact governed prompt, presses Enter, and
then restores Bekki to the foreground while ChatGPT stays readable behind it.
It does not use browser/CDP, coordinate clicks, or
the unverified off-screen send experiments from later development builds.

Changes:

- return focus to Bekki and wait through readable background UI Automation;
- minimize ChatGPT only after the answer is captured;
- use pointer-width-safe clipboard API signatures on 64-bit Windows;
- treat clipboard read/copy failures as a recoverable UIA fallback;
- reject `You said:`, prompt echoes, tiny UI labels, and 404/provider errors;
- require a substantive stable answer before returning `COMPLETED`;
- preserve the source question's language for direct and NERV-curiosity asks;
- never append English to a Chinese question unless translation is requested.

Expected live path:

1. `EXTERNAL AI DESKTOP WINDOW`
2. `EXTERNAL AI DESKTOP INPUT`
3. `EXTERNAL AI DESKTOP WRITE ROUTE`
4. `EXTERNAL AI DESKTOP PROMPT SENT`
5. `EXTERNAL AI DESKTOP BACKGROUND previous_window_restored`
6. `EXTERNAL AI DESKTOP ANSWER RECEIVED`
7. `EXTERNAL AI DESKTOP BACKGROUND minimized_after_read`

The returned ChatGPT answer remains `UNVERIFIED_EXTERNAL_AI` and is not written
to Knowledge automatically.
