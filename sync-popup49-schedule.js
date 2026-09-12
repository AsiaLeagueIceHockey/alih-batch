const axios = require('axios');
const { createClient } = require('@supabase/supabase-js');
const { decodePopupHtml, parsePopupScoresHtml } = require('./lib/popup-scores');

const TARGET_SEASON = process.env.TARGET_SEASON;
const SOURCE_POPUP_ID = Number(process.env.SOURCE_POPUP_ID);
const EXPECTED_GAME_COUNT = Number(process.env.EXPECTED_GAME_COUNT);
const DRY_RUN = process.env.DRY_RUN !== 'false';
const ALLOW_WRITE = process.env.ALLOW_WRITE === 'true';

const POPUP49_VENUES = {
  Yamanashi: 'Kofu',
  Higashifushimi: 'Nishitokyo',
};

const TIME_CORRECTIONS = new Map([
  [82, { internalGameNo: 83, before: '2027-01-23T15:00:00+09:00', after: '2027-01-23T14:00:00+09:00' }],
  [85, { internalGameNo: 86, before: '2027-01-24T14:00:00+09:00', after: '2027-01-24T19:00:00+09:00' }],
  [86, { internalGameNo: 84, before: '2027-01-24T13:00:00+09:00', after: '2027-01-24T14:00:00+09:00' }],
  [93, { internalGameNo: 93, before: '2027-02-07T13:00:00+09:00', after: '2027-02-07T14:00:00+09:00' }],
  [108, { internalGameNo: 108, before: '2027-02-28T14:00:00+09:00', after: '2027-02-28T13:00:00+09:00' }],
]);

const VENUE_CORRECTIONS = new Map([
  [88, { internalGameNo: 88, before: 'Hachinohe', after: 'Nishitokyo' }],
  [89, { internalGameNo: 89, before: 'Hachinohe', after: 'Nishitokyo' }],
]);

function requireEnvironment() {
  if (!/^\d{4}-\d{2}$/.test(TARGET_SEASON || '')) {
    throw new Error('TARGET_SEASON must be an explicit YYYY-YY value');
  }
  if (!Number.isInteger(SOURCE_POPUP_ID) || SOURCE_POPUP_ID <= 0) {
    throw new Error('SOURCE_POPUP_ID must be a positive integer');
  }
  if (!Number.isInteger(EXPECTED_GAME_COUNT) || EXPECTED_GAME_COUNT <= 0) {
    throw new Error('EXPECTED_GAME_COUNT must be a positive integer');
  }
  if (!DRY_RUN && !ALLOW_WRITE) {
    throw new Error('Refusing DB write without ALLOW_WRITE=true');
  }
  if (!process.env.SUPABASE_URL || !(process.env.SUPABASE_SERVICE_KEY || (DRY_RUN && process.env.SUPABASE_KEY))) {
    throw new Error('SUPABASE_URL and SUPABASE_SERVICE_KEY are required (SUPABASE_KEY is accepted for read-only dry-runs only)');
  }
}

function kstDate(value) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date(value));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function eventKey({ homeTeamId, awayTeamId, matchAt }) {
  return `${homeTeamId}|${awayTeamId}|${kstDate(matchAt)}`;
}

function sameTimestamp(left, right) {
  return new Date(left).getTime() === new Date(right).getTime();
}

function canonicalVenue(value) {
  return POPUP49_VENUES[value] || value;
}

function assertAllowedScheduleMetadataChange(schedule, source, desiredVenue) {
  if (!sameTimestamp(schedule.match_at, source.matchAt)) {
    const correction = TIME_CORRECTIONS.get(source.officialGameNo);
    if (!correction
      || correction.internalGameNo !== schedule.game_no
      || !sameTimestamp(schedule.match_at, correction.before)
      || !sameTimestamp(source.matchAt, correction.after)) {
      throw new Error(`Unexpected time change for popup ${source.officialGameNo}, internal ${schedule.game_no}`);
    }
  }

  if (schedule.match_place !== desiredVenue) {
    const correction = VENUE_CORRECTIONS.get(source.officialGameNo);
    if (!correction
      || correction.internalGameNo !== schedule.game_no
      || schedule.match_place !== correction.before
      || desiredVenue !== correction.after) {
      throw new Error(`Unexpected venue change for popup ${source.officialGameNo}, internal ${schedule.game_no}`);
    }
  }
}

function reconcileSchedules({
  sourceRows,
  schedules,
  teamIds,
  expectedGameCount = EXPECTED_GAME_COUNT,
  sourcePopupId = SOURCE_POPUP_ID,
}) {
  if (!Number.isInteger(expectedGameCount) || expectedGameCount <= 0) {
    throw new Error('expectedGameCount must be a positive integer');
  }
  if (!Number.isInteger(sourcePopupId) || sourcePopupId <= 0) {
    throw new Error('sourcePopupId must be a positive integer');
  }
  if (sourceRows.length !== expectedGameCount || schedules.length !== expectedGameCount) {
    throw new Error(`Expected ${expectedGameCount} source and database schedule rows, received ${sourceRows.length} and ${schedules.length}`);
  }

  const dbByEvent = new Map();
  for (const schedule of schedules) {
    const key = eventKey({
      homeTeamId: schedule.home_alih_team_id,
      awayTeamId: schedule.away_alih_team_id,
      matchAt: schedule.match_at,
    });
    if (dbByEvent.has(key)) {
      throw new Error(`Ambiguous database schedule event: ${key}`);
    }
    dbByEvent.set(key, schedule);
  }

  const matchedIds = new Set();
  const updates = [];
  for (const source of sourceRows) {
    const homeTeamId = teamIds.get(source.mappedHomeName);
    const awayTeamId = teamIds.get(source.mappedAwayName);
    if (!homeTeamId || !awayTeamId) {
      throw new Error(`Missing DB team mapping: ${source.mappedHomeName} vs ${source.mappedAwayName}`);
    }

    const key = eventKey({ homeTeamId, awayTeamId, matchAt: source.matchAt });
    const schedule = dbByEvent.get(key);
    if (!schedule) {
      throw new Error(`No database schedule event for popup Game No ${source.officialGameNo}`);
    }
    if (matchedIds.has(schedule.id)) {
      throw new Error(`Multiple popup games matched schedule id ${schedule.id}`);
    }
    matchedIds.add(schedule.id);

    if (schedule.source_popup_id !== null && schedule.source_popup_id !== sourcePopupId) {
      throw new Error(`Schedule ${schedule.id} already belongs to popup ${schedule.source_popup_id}`);
    }
    if (schedule.source_game_no !== null && schedule.source_game_no !== source.officialGameNo) {
      throw new Error(`Schedule ${schedule.id} already has a different official Game No`);
    }

    const matchPlace = canonicalVenue(source.matchPlace);
    assertAllowedScheduleMetadataChange(schedule, source, matchPlace);
    const payload = {
      source_popup_id: sourcePopupId,
      source_game_no: source.officialGameNo,
      season_phase: 'regular',
      match_at: source.matchAt,
      match_place: matchPlace,
    };

    const changed = Object.entries(payload).some(([keyName, value]) => {
      if (keyName === 'match_at') return !sameTimestamp(schedule[keyName], value);
      return schedule[keyName] !== value;
    });
    if (changed) updates.push({ schedule, source, payload });
  }

  if (matchedIds.size !== schedules.length) {
    throw new Error(`Unmatched DB schedules: expected ${schedules.length}, matched ${matchedIds.size}`);
  }

  return updates;
}

async function main() {
  requireEnvironment();
  const sourceUrl = `https://www.alhockey.com/popup/${SOURCE_POPUP_ID}/scores.html`;
  const response = await axios.get(sourceUrl, { responseType: 'arraybuffer', timeout: 20_000 });
  const parsed = parsePopupScoresHtml(decodePopupHtml(response.data), {
    targetSeason: TARGET_SEASON,
    popupId: SOURCE_POPUP_ID,
    seasonPhase: 'regular',
    expectedGameCount: EXPECTED_GAME_COUNT,
  });

  const supabaseKey = process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_KEY;
  const supabase = createClient(process.env.SUPABASE_URL, supabaseKey, {
    auth: { persistSession: false },
  });
  const [{ data: teams, error: teamsError }, { data: schedules, error: schedulesError }] = await Promise.all([
    supabase.from('alih_teams').select('id, english_name'),
    supabase.from('alih_schedule')
      .select('id, game_no, season, game_status, match_at, match_place, home_alih_team_id, away_alih_team_id, source_popup_id, source_game_no, season_phase')
      .eq('season', TARGET_SEASON)
      .order('game_no'),
  ]);
  if (teamsError) throw new Error(`Unable to read teams: ${teamsError.message}`);
  if (schedulesError) throw new Error(`Unable to read schedules: ${schedulesError.message}`);

  const teamIds = new Map(teams.map((team) => [team.english_name, team.id]));
  const updates = reconcileSchedules({
    sourceRows: parsed.rows,
    schedules,
    teamIds,
    expectedGameCount: EXPECTED_GAME_COUNT,
    sourcePopupId: SOURCE_POPUP_ID,
  });
  const report = {
    mode: DRY_RUN ? 'dry-run' : 'write',
    targetSeason: TARGET_SEASON,
    popupId: SOURCE_POPUP_ID,
    sourceRows: parsed.rows.length,
    sourceHash: parsed.normalizedScheduleHash,
    matchedSchedules: schedules.length,
    updates: updates.length,
    officialGameNumbersChanged: updates.filter(({ schedule, source }) => schedule.source_game_no !== source.officialGameNo).length,
    timeCorrections: updates.filter(({ schedule, payload }) => !sameTimestamp(schedule.match_at, payload.match_at)).length,
    venueCorrections: updates.filter(({ schedule, payload }) => schedule.match_place !== payload.match_place).length,
  };

  if (!DRY_RUN) {
    for (const { schedule, payload } of updates) {
      const { error } = await supabase.from('alih_schedule').update(payload).eq('id', schedule.id);
      if (error) throw new Error(`Unable to update schedule ${schedule.id}: ${error.message}`);
    }
  }

  console.log(JSON.stringify(report));
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}

module.exports = {
  canonicalVenue,
  eventKey,
  assertAllowedScheduleMetadataChange,
  reconcileSchedules,
};
