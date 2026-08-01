# ADR 0004: Timeline Density And Day-Level Overrides

- Status: Accepted
- Date: 2026-07-31

## Context

The timeline UI became noisy due to boxed rows and repeated metadata headings. A known day (`2026-07-01`) also contained a noisy note dump that should not be treated as authoritative.

## Decision

- Simplify timeline rendering to timestamp-first lines.
- Remove repeated "time | type | ref" headers per row.
- Keep screenshot context inline with image and editable summary.
- Apply explicit per-day suppression overrides where data quality is known to be bad.

## Consequences

- Cleaner visual scan for daily review.
- Better signal-to-noise ratio in both dashboard and generated Confluence rows.
- Overrides are explicit, auditable, and easily removable when source data is corrected.