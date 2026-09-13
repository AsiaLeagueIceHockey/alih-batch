const axios = require('axios');
const { createClient } = require('@supabase/supabase-js');
const { decodePopupHtml, parsePopupScoresHtml } = require('./lib/popup-scores');

const TARGET_SEASON = process.env.TARGET_SEASON;
const SOURCE_POPUP_ID = Number(process.env.SOURCE_POPUP_ID);
const EXPECTED_GAME_COUNT = Number(process.env.EXPECTED_GAME_COUNT);
const DRY_RUN = process.env.DRY_RUN !== 'false';
const ALLOW_WRITE = process.env.ALLOW_WRITE === 'true';

function requireEnvironment() {
  if (!/^\d{4}-\d{2}$/.test(TARGET_SEASON || '')) throw new Error('TARGET_SEASON must be an explicit YYYY-YY value');
  if (!Number.isInteger(SOURCE_POPUP_ID) || SOURCE_POPUP_ID <= 0) throw new Error('SOURCE_POPUP_ID must be a positive integer');
  if (!Number.isInteger(EXPECTED_GAME_COUNT) || EXPECTED_GAME_COUNT <= 0) throw new Error('EXPECTED_GAME_COUNT must be a positive integer');
  if (!DRY_RUN && !ALLOW_WRITE) throw new Error('Refusing result write without ALLOW_WRITE=true');
  if (!process.env.SUPABASE_URL || !(process.env.SUPABASE_SERVICE_KEY || (DRY_RUN && process.env.SUPABASE_KEY))) {
    throw new Error('SUPABASE_URL and SUPABASE_SERVICE_KEY are required (SUPABASE_KEY is accepted for dry-runs only)');
  }
}

function reconcileFinishedResults(sourceRows, schedules, {
  sourcePopupId = SOURCE_POPUP_ID,
  expectedGameCount = EXPECTED_GAME_COUNT,
} = {}) {
  if (!Number.isInteger(sourcePopupId) || sourcePopupId <= 0) throw new Error('sourcePopupId must be a positive integer');
  if (!Number.isInteger(expectedGameCount) || expectedGameCount <= 0) throw new Error('expectedGameCount must be a positive integer');
  const schedulesBySourceGameNo = new Map();
  for (const schedule of schedules) {
    if (schedule.source_popup_id !== sourcePopupId || !Number.isInteger(schedule.source_game_no)) {
      throw new Error(`Schedule ${schedule.id} is missing the expected popup ${sourcePopupId} mapping`);
    }
    if (schedulesBySourceGameNo.has(schedule.source_game_no)) {
      throw new Error(`Duplicate source Game No ${schedule.source_game_no} in schedules`);
    }
    schedulesBySourceGameNo.set(schedule.source_game_no, schedule);
  }
  if (schedulesBySourceGameNo.size !== expectedGameCount) {
    throw new Error(`Expected ${expectedGameCount} mapped schedules, received ${schedulesBySourceGameNo.size}`);
  }

  const updates = [];
  for (const source of sourceRows.filter((row) => row.gameStatus === 'Game Finished')) {
    const schedule = schedulesBySourceGameNo.get(source.officialGameNo);
    if (!schedule) throw new Error(`Official finished Game No ${source.officialGameNo} has no schedule mapping`);
    const existingScores = [schedule.home_alih_team_score, schedule.away_alih_team_score];
    const officialScores = [source.homeScore, source.awayScore];
    const hasExistingScore = existingScores.some((score) => score !== null && score !== undefined);
    if (hasExistingScore && (existingScores[0] !== officialScores[0] || existingScores[1] !== officialScores[1])) {
      throw new Error(`Score conflict for internal Game No ${schedule.game_no}: DB ${existingScores.join(':')} vs official ${officialScores.join(':')}`);
    }
    if (schedule.game_status === 'Game Finished' && !hasExistingScore) {
      throw new Error(`Finished schedule ${schedule.game_no} is missing a score`);
    }
    if (schedule.game_status !== 'Game Finished' || !hasExistingScore) {
      updates.push({
        id: schedule.id,
        gameNo: schedule.game_no,
        sourceGameNo: source.officialGameNo,
        payload: {
          home_alih_team_score: source.homeScore,
          away_alih_team_score: source.awayScore,
          game_status: 'Game Finished',
        },
      });
    }
  }
  return updates;
}

async function main() {
  requireEnvironment();
  const response = await axios.get(`https://www.alhockey.com/popup/${SOURCE_POPUP_ID}/scores.html`, {
    responseType: 'arraybuffer', timeout: 20_000,
  });
  const parsed = parsePopupScoresHtml(decodePopupHtml(response.data), {
    targetSeason: TARGET_SEASON,
    popupId: SOURCE_POPUP_ID,
    seasonPhase: 'regular',
    expectedGameCount: EXPECTED_GAME_COUNT,
  });
  const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_KEY, {
    auth: { persistSession: false },
  });
  const { data: schedules, error } = await supabase
    .from('alih_schedule')
    .select('id, game_no, source_popup_id, source_game_no, home_alih_team_score, away_alih_team_score, game_status')
    .eq('season', TARGET_SEASON)
    .order('game_no');
  if (error) throw new Error(`Unable to read schedules: ${error.message}`);

  const updates = reconcileFinishedResults(parsed.rows, schedules, {
    sourcePopupId: SOURCE_POPUP_ID,
    expectedGameCount: EXPECTED_GAME_COUNT,
  });
  if (!DRY_RUN) {
    for (const update of updates) {
      const { error: updateError } = await supabase.from('alih_schedule').update(update.payload).eq('id', update.id);
      if (updateError) throw new Error(`Unable to update Game No ${update.gameNo}: ${updateError.message}`);
    }
  }
  console.log(JSON.stringify({
    mode: DRY_RUN ? 'dry-run' : 'write',
    targetSeason: TARGET_SEASON,
    sourceFinishedGames: parsed.rows.filter((row) => row.gameStatus === 'Game Finished').length,
    schedulesToUpdate: updates.length,
    updates: updates.map(({ gameNo, sourceGameNo, payload }) => ({ gameNo, sourceGameNo, ...payload })),
  }));
}

if (require.main === module) {
  main().catch((error) => { console.error(error.message); process.exit(1); });
}

module.exports = { reconcileFinishedResults };
