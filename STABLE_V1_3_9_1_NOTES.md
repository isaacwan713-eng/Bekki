# Bekki Stable V1.3.9.1

Build ID: `bekki-stable-v1-3-9-1-20260824`

This hotfix resolves a MAGI contract collision found while testing:

`去小红书搜索最近一周美国麦当劳新出的玩具`

Both models correctly recognized explicit Xiaohongshu research but also marked
the subject as product recommendation research. Those closed routes are
mutually exclusive, so the request stopped before Melchior.

Named-platform research now has an explicit contract: once MAGI's AI judgment
selects `SOCIAL_RESEARCH`, `search_scope` must also be `SOCIAL_RESEARCH` and
`recommendation_domain` must be null. The bounded recovery AI receives the same
constraint and the rejected route for correction. Python still validates only
the closed result and does not infer intent from McDonald's, toy, restaurant,
or product keywords.

The V1.3.9 five-to-seven post summaries and Top 3 visible-engagement ranking
remain unchanged. The UI is unchanged.
