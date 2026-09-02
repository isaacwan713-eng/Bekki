# Bilibili Native Response V1.10.33

V1.10.32 confirmed that Bekki was presenting the connected Microsoft Edge
version correctly and rejecting the unrelated legacy BV link. The diagnostic
counts nevertheless stayed at `anchors=46`, `video_links=1`, and
`video_cards=0`, proving that Bilibili had supplied a navigation shell rather
than a result grid.

V1.10.33 adds two native recovery paths without introducing another search
provider:

- Bilibili searches run in Bekki's dedicated normal Edge process in minimized
  mode. If the V1.10.32 headless process is still running, Bekki replaces it
  before opening the search page.
- Before navigation, Bekki attaches a listener for successful search responses
  issued by the Bilibili page itself. A bounded parser accepts only public video
  rows with a real Bilibili video URL or BV identifier, strips result markup,
  normalizes the thumbnail, and preserves the literal title and metadata for
  the existing evidence pipeline.

The native-response path is not a separate third-party API call and needs no
API key. Nonzero platform codes, risk-control replies, malformed rows, foreign
hosts, login, consent, CAPTCHA, and other access controls fail closed. Selected
candidates are still opened on their real Bilibili video pages by the existing
detail reader before the final social evidence and cards are produced.

Useful diagnostics:

- `[SOCIAL BILIBILI BROWSER RESTART] mode=headed` means an old managed
  headless process was replaced.
- `[SOCIAL BILIBILI RESPONSE] candidates=N` means the page's successful native
  response yielded `N` bounded video candidates.
- `[SOCIAL BILIBILI RESPONSE MERGE] candidates=N` means those candidates were
  added to the literal result-card evidence.
- `[SOCIAL BILIBILI RESPONSE REJECTED] code=...` means Bilibili returned a
  non-success platform code; Bekki did not use that response.

A minimized Edge window may briefly appear during a Bilibili search. Bekki
closes that dedicated browser when the social-search pass finishes.
