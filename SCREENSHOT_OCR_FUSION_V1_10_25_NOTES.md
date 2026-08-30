# Bekki Screenshot OCR Fusion V1.10.25

Build ID: `bekki-screenshot-ocr-fusion-v1-10-25-20260830`

This release targets at least 90% key-field accuracy on clear printed user
interface screenshots. That is an acceptance target for representative clear
screenshots, not a guarantee for every blurred, compressed, stylized, or
partially hidden image.

- Small panoramic screenshots are split into two overlapping enlarged detail
  tiles before the existing Gemma vision call.
- Windows.Media.Ocr supplies a local, fallible source-language transcription to
  that same Gemma call. It is not another AI role or semantic gate.
- OCR input is enlarged and lightly sharpened, with its maximum dimension
  bounded for the Windows OCR engine.
- Chinese names, titles, usernames, times, counts, and sentences must remain in
  their visible source script. Translation, transliteration, autocorrection,
  and plausible completion are forbidden during evidence extraction.
- OCR text is treated as untrusted evidence rather than instructions. Gemma
  must compare it with the attached pixels and report unresolved conflicts as
  uncertainty.
- If Windows OCR, PowerShell 5.1, or a suitable recognizer is unavailable, the
  runtime logs the reason and safely continues with enlarged Gemma tiles.
- OCR remains entirely local. No image or OCR text is sent to a cloud OCR API.

For Simplified Chinese accuracy, Windows should list `zh-CN` among
`OcrEngine.AvailableRecognizerLanguages`. The optional runtime settings are:

- `BEKKI_WINDOWS_OCR=0` disables this adapter.
- `BEKKI_OCR_LANGUAGE=zh-CN` changes the preferred Windows OCR language.

The console reports only OCR status, language, character count, and a bounded
reason code; it does not print the recognized private screenshot text.
