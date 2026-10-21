---
date: 2026-10-22
category: bug
source: harness-implement
---

# Fail closed when an official standings team is unmapped

## Situation

The popup 49 standings source shortened HL Anyang's label from
`HL ANYANG ICE HOCKEY CLUB` to `HL ANYANG`. The writer logged a warning,
skipped that row, upserted the other five teams, and still exited successfully.
Production therefore kept HL Anyang's seeded zero-game row while every other
team continued updating.

## What we learned

An allowed total row-count range does not prove that every source row was
mapped. A scraper that silently skips an unknown source identity can report a
green workflow while preserving stale production data for exactly one entity.

## Next time

Keep source-name aliases in a unit-tested mapping and raise on any unmapped
source team or missing database identity. Validate the current official HTML in
dry-run mode after a mapping change before enabling writes.
