# Responsive Conversation Width V1.10.41.5

- Assistant Markdown bubbles now follow the live chat viewport.
- The compact width remains 350 px; wide windows scale smoothly to 760 px.
- Evidence-card context, screenshots, video covers and sampled frames resize
  as one bound result block.
- Short user messages stay naturally compact.
- Existing messages reflow after maximize, restore, sidebar and task-drawer
  size changes.
- Curiosity Writer generation budget was raised from 700 to 1200 tokens.
- Invalid or truncated Writer JSON receives one 1600-token retry.
- `no_curiosity` now means the model deliberately returned `proposal=null`;
  malformed output reports `writer_invalid_output` instead.
