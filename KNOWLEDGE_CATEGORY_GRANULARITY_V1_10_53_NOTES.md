# Knowledge Category Granularity V1.10.53

Build: `bekki-knowledge-category-granularity-v1-10-53-20260905`

## What changes

- Every active Topic now uses exactly two reusable category nodes beneath its
  fixed domain: a broad family followed by a stable entity or knowledge kind.
- A legacy one-node path remains readable and is queued for a safe refinement.
  Its domain and existing first node are preserved; the assessor adds only the
  missing second node.
- Existing two-node paths that meet the new granularity contract are locked
  during ordinary lifecycle and interest reassessment. An explicit maintenance
  call is required to reclassify one.
- Existing category IDs and labels are reuse-first. The model-output gate and
  the final storage boundary both reject sibling ID/label drift and common
  singular/plural duplicates.
- The assessor is told to group the same durable kind together rather than
  splitting it by country, language, franchise, source website, date, or
  current-versus-historical status. Human idol groups and virtual idols remain
  distinct kinds; open-source robotics can be distinguished within robotics.

## Safe migration behavior

When a Topic already has current fact types, L1-L5 layers, and a current
lifecycle assessment, the first-run refinement changes only its browse
classification. Bekki preserves the exact lifecycle object, claims, sources,
relationships, temporal scopes, and Knowledge layers. A classification-only
refinement also cannot create a new Curiosity question by itself.

The old one-node classification is retained in bounded
`classification_history` for auditability. The derived category index is then
rebuilt from authoritative active claims.

## First run

Start Bekki normally and leave it idle until each pending Topic emits a line
like:

```text
[NERV TOPIC LIFECYCLE] ... layered=0 classified=0 category_refined=true
```

With the five Topics from V1.10.52.1, one bounded lifecycle pass can refine all
five. Exact category IDs remain AI-selected and reuse-first; the expected
shape is comparable to:

- `culture_entertainment/music_entertainment/<human-idol-kind>` for AKB48,
  SNH48, and TWICE;
- `culture_entertainment/music_entertainment/<virtual-idol-kind>` for 四禧丸子;
- `computer_science/robotics_tech/<open-source-robotics-kind>` for Microduck.

## Validation

After the refinement lines finish, close Bekki and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\TEST_KNOWLEDGE_CATEGORY_GRANULARITY_V1_10_53.ps1
```

The validator is read-only against the live SQLite database. It prints every
Topic-to-category path and fails on unfinished one-level paths, duplicate
sibling categories, missing layers/fact types, index mismatches, payload hash
errors, or SQLite integrity failure.

## Unchanged scope

This release does not change Bilibili navigation, UP-profile behavior, search,
video resolution, playback, browser profiles, UI fonts, or Companion Watch.
