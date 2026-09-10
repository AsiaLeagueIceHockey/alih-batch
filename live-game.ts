/**
 * Legacy writer intentionally disabled for 2026-27.
 *
 * It previously derived a score URL from game_no and wrote game details by
 * global game_no, both unsafe once seasons reuse numbers. Live score updates
 * now belong to alih/supabase/functions/live-game after the schedule_id
 * contract, source parser fixtures, and canary gates are complete.
 */

throw new Error(
  'Legacy live-game.ts is disabled. Use the season-aware Edge Function launch plan instead.'
);
