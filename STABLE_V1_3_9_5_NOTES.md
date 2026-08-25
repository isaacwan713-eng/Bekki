# Bekki Stable V1.3.9.5

Build ID: `bekki-stable-v1-3-9-5-20260824`

This patch changes social-result selection from "first seven, then rank" to
"rank all verified recent candidates, then select the strongest seven". The
single interaction value visibly shown on the social search page is the
primary ranking signal. Unknown values remain behind known values, and equal
values preserve their page order.

The final five-to-seven summaries and Top 3 cards use the same high-to-low
interaction order. Bekki explains once that this is a search-page-visible
interaction value whose type is not labeled; it is not guessed or split into
likes, comments, or shares.

The validator also rejects repeated AI output for an already accepted post
title. The V1.3.9.4 per-post screenshots, image descriptions, strict labeled
engagement rules, untranslated names, and stable UI remain unchanged.
