# Bekki Stable V1.3.9.3

Build ID: `bekki-stable-v1-3-9-3-20260824`

This patch addresses two issues observed after V1.3.9.2 successfully produced
seven post summaries and three social cards:

- Social vision repeated the same OCR strings until its JSON was truncated.
- Chinese social requests sometimes received English image and post summaries.

Visual extraction is now bounded to three observations, four unique short OCR
strings per observation, and compact description/relevance fields. Its output
budget is also large enough to close the bounded JSON object. Social vision and
post-introduction packets carry an explicit narrative-language contract; a
Chinese request requires Chinese narrative fields while exact post titles,
proper names, and evidence quotations remain untranslated.

The validator remains strict about likes, comments, and shares. A bare label
such as `Comment` is not sufficient evidence for a numeric comment count, and
an unlabeled search-grid count remains generic visible interaction.

The V1.3.9.2 virtualized title resolver, five-to-seven direct summaries, Top 3
cards, and stable UI remain unchanged.
