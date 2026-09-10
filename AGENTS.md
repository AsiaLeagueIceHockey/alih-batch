# ALIH batch agent guidance

Before modifying this repository, read the complete 2026-27 operations source of truth in `../alih/docs/2026-27-operations-audit.md`.
Continue the unfinished launch work only through `../alih/.omx/plans/2026-27-terra-execution-plan.md` and do not skip its phase gates.

- Preserve all 2025-26 data and never run a batch writer without an explicit `TARGET_SEASON`.
- Treat `game_no` as season-local display data; use the immutable `alih_schedule.id` (`schedule_id`) for cross-table identity.
- Keep official score pages in `score_url` and YouTube viewing links in `live_url`.
- Default schedule synchronization to `DRY_RUN=true`.
- Do not enable GitHub Actions schedules, deploy Edge Functions, apply production migrations, or change secrets unless that production action is explicitly in scope and its rollback is known.
- Never print or commit `.env`, service-role keys, PATs, VAPID private keys, Slack webhooks, or AI API keys.
- Verify both this repository and the sibling frontend repository when changing a shared database contract.
