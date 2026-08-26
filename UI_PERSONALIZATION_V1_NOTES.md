# Bekki UI Personalization V1

Build: `bekki-ui-personalization-v1-20260826`

This patch adds a small appearance layer without restructuring Bekki's stable
desktop layout.

## New controls

- Open the gear button in the top-right header.
- Choose the font used by chat bubbles and the message editor.
- Set the chat font size from 11 to 20.
- Choose a PNG, JPG, JPEG, or WebP image for Bekki's avatar.
- Preview typography and avatar changes before saving.
- Restore the bundled Bekki avatar and default typography.

## Persistence and boundaries

- Appearance settings are saved separately in `data/ui_preferences.json`.
- A selected avatar is validated and copied into `data` with a 15 MB limit.
- The stable installer already preserves `data`, so personalization survives
  future source updates.
- Applying settings updates existing visible messages and the input editor; a
  restart is not required.
- Conversation history and NERV Profile/Knowledge stores are not modified by
  appearance changes.

## Validation

The patch includes pure settings-store tests and AST UI contract tests in
`tests/test_ui_preferences.py` and
`tests/test_ui_personalization_contract.py`.
