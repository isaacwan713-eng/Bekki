# Social Claim Grounding V1.10.41.7

- Reconciles platformless `SOCIAL_RESEARCH` to MAGI's existing
  `CLAIM_CHECK`, `FACT_LOOKUP`, or `NEWS_FEED` search scope.
- Never guesses a social platform that the user did not name.
- Stops claim-check and social-research failures before the final writer can
  turn zero evidence into an unsupported conclusion.
- Preserves visibly named co-subjects such as `李艺彤×黄婷婷` while keeping
  unlabeled face-to-name mapping uncertain.
- Retries malformed Curiosity Writer JSON with a compact 4096-context recovery
  prompt and packet rather than repeating the 13.7 KB primary prompt.
- Includes User Message Completeness V1.10.41.6.
