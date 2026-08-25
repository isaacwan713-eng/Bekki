# Bekki Stable V1.3.5

Build: `bekki-stable-v1-3-5-20260824`

This release fixes the live case where a normal request for good San Gabriel
Chinese restaurants was routed to NEWS_FEED and produced an inappropriate news
summary.

- Reliable 12B MAGI now returns a closed AI-selected search subtype.
- It also returns a recommendation domain only when the selected subtype needs
  one.
- Open-ended restaurant selection is RECOMMENDATION_RESEARCH + RESTAURANT.
- This reliable result bypasses compact Melchior, just like explicit named
  social-platform research already does.
- Current-news requests remain NEWS_FEED; single changing facts and explicit
  claims remain distinct.
- Python only validates the closed AI contract. It does not select the route by
  words such as “restaurant”, “recommend”, or “news”.
- V1.3.4.1 social title location and the stable UI are unchanged.

Expected live markers for `推荐几家圣盖博好吃的中餐厅`:

```text
[MAGI ROUTE] ... "search_scope": "RECOMMENDATION_RESEARCH" ...
[MELCHIOR RECOMMENDATION ROUTE] RESTAURANT
[melchior MODE] RECOMMENDATION_RESEARCH
```
