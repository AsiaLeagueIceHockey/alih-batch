const assert = require('node:assert/strict');
const test = require('node:test');
const { parsePopupScoresHtml } = require('../lib/popup-scores');
const { canonicalVenue, reconcileSchedules } = require('../sync-popup49-schedule');
const { reconcileFinishedResults } = require('../sync-popup49-results');

const fixture = `
<html><head><title>Asia League Ice Hockey 2026-2027 / Regular | Scores Game Sheet</title></head><body>
  <span class="black15b">September</span>
  <table><tr><th>Game No.</th></tr>
    <tr><td>12</td><td>Sat</td><td>1</td><td>EAGLES</td><td></td><td>ICEBUCKS</td><td>&lt; 1 &gt;</td><td>Tomakomai</td><td>15:00</td><td><a href="/sheet/49/game/ogs1.html">Game Sheet</a></td></tr>
    <tr><td>2</td><td>GRITS</td><td>2 - 3</td><td>STARS</td><td>&lt; 1 &gt;</td><td>Shinyokohama</td><td>15:00</td><td></td></tr>
  </table>
  <span class="black15b">January</span>
  <table><tr><th>Game No.</th></tr>
    <tr><td>2</td><td>Sun</td><td>3</td><td>HL ANYANG</td><td></td><td>FREEBLADES</td><td>&lt; 1 &gt;</td><td>Anyang</td><td>18:30</td><td></td></tr>
  </table>
</body></html>`;

const options = {
  targetSeason: '2026-27',
  popupId: 49,
  expectedGameCount: 3,
};

test('parses official game numbers, KST dates, scores, and game-sheet URLs', () => {
  const result = parsePopupScoresHtml(fixture, options);

  assert.equal(result.rows.length, 3);
  assert.deepEqual(result.rows.map((row) => row.officialGameNo), [1, 2, 3]);
  assert.equal(result.rows[0].matchAt, '2026-09-12T15:00:00+09:00');
  assert.equal(result.rows[1].gameStatus, 'Game Finished');
  assert.equal(result.rows[1].homeScore, 2);
  assert.equal(result.rows[1].awayScore, 3);
  assert.equal(result.rows[2].matchAt, '2027-01-02T18:30:00+09:00');
  assert.equal(result.rows[0].sourceGameSheetUrl, 'https://www.alhockey.com/sheet/49/game/ogs1.html');
  assert.match(result.normalizedScheduleHash, /^[a-f0-9]{64}$/);
});

test('fails closed for a title from another season', () => {
  assert.throws(
    () => parsePopupScoresHtml(fixture.replace('2026-2027', '2025-2026'), options),
    /Unexpected popup title/,
  );
});

test('fails closed for an unknown source team', () => {
  assert.throws(
    () => parsePopupScoresHtml(fixture.replace('EAGLES', 'UNKNOWN TEAM'), options),
    /Unknown team mapping/,
  );
});

test('fails closed for duplicate official game numbers', () => {
  assert.throws(
    () => parsePopupScoresHtml(fixture.replace('<td>3</td><td>HL ANYANG', '<td>2</td><td>HL ANYANG'), options),
    /unique Game No values/,
  );
});

test('canonicalizes only known popup venue aliases', () => {
  assert.equal(canonicalVenue('Yamanashi'), 'Kofu');
  assert.equal(canonicalVenue('Higashifushimi'), 'Nishitokyo');
  assert.equal(canonicalVenue('Tomakomai'), 'Tomakomai');
});

test('fails closed when a source row cannot be matched to exactly one schedule event', () => {
  const sourceRows = [{
    officialGameNo: 1,
    mappedHomeName: 'EAGLES',
    mappedAwayName: 'ICEBUCKS',
    matchAt: '2026-09-12T15:00:00+09:00',
    matchPlace: 'Tomakomai',
  }];
  const schedules = [{
    id: 1,
    game_no: 1,
    match_at: '2026-09-12T15:00:00+09:00',
    match_place: 'Tomakomai',
    home_alih_team_id: 2,
    away_alih_team_id: 5,
    source_popup_id: null,
    source_game_no: null,
    season_phase: 'regular',
  }, {
    id: 2,
    game_no: 2,
    match_at: '2026-09-12T15:00:00+09:00',
    match_place: 'Tomakomai',
    home_alih_team_id: 2,
    away_alih_team_id: 5,
    source_popup_id: null,
    source_game_no: null,
    season_phase: 'regular',
  }];

  assert.throws(() => reconcileSchedules({
    sourceRows,
    schedules,
    teamIds: new Map([['EAGLES', 2], ['ICEBUCKS', 5]]),
    expectedGameCount: 1,
    sourcePopupId: 49,
  }), /Expected 1 source and database schedule rows/);
});

test('creates a source-only update for a schedule with unchanged metadata', () => {
  const sourceRows = [{
    officialGameNo: 1,
    mappedHomeName: 'EAGLES',
    mappedAwayName: 'ICEBUCKS',
    matchAt: '2026-09-12T15:00:00+09:00',
    matchPlace: 'Tomakomai',
  }];
  const schedules = [{
    id: 1,
    game_no: 1,
    match_at: '2026-09-12T15:00:00+09:00',
    match_place: 'Tomakomai',
    home_alih_team_id: 2,
    away_alih_team_id: 5,
    source_popup_id: null,
    source_game_no: null,
    season_phase: 'regular',
  }];

  const updates = reconcileSchedules({
    sourceRows,
    schedules,
    teamIds: new Map([['EAGLES', 2], ['ICEBUCKS', 5]]),
    expectedGameCount: 1,
    sourcePopupId: 49,
  });

  assert.deepEqual(updates[0].payload, {
    source_popup_id: 49,
    source_game_no: 1,
    season_phase: 'regular',
    match_at: '2026-09-12T15:00:00+09:00',
    match_place: 'Tomakomai',
  });
});

test('permits only the documented popup 49 time correction', () => {
  const updates = reconcileSchedules({
    sourceRows: [{
      officialGameNo: 82,
      mappedHomeName: 'GRITS',
      mappedAwayName: 'ICEBUCKS',
      matchAt: '2027-01-23T14:00:00+09:00',
      matchPlace: 'Shinyokohama',
    }],
    schedules: [{
      id: 768,
      game_no: 83,
      match_at: '2027-01-23T15:00:00+09:00',
      match_place: 'Shinyokohama',
      home_alih_team_id: 4,
      away_alih_team_id: 5,
      source_popup_id: null,
      source_game_no: null,
      season_phase: 'regular',
    }],
    teamIds: new Map([['GRITS', 4], ['ICEBUCKS', 5]]),
    expectedGameCount: 1,
    sourcePopupId: 49,
  });

  assert.equal(updates[0].payload.match_at, '2027-01-23T14:00:00+09:00');
  assert.equal(updates[0].payload.source_game_no, 82);
});

test('updates only an official finished game with no conflicting stored score', () => {
  const updates = reconcileFinishedResults([
      { officialGameNo: 1, gameStatus: 'Game Finished', homeScore: 3, awayScore: 2 },
      { officialGameNo: 2, gameStatus: 'Scheduled', homeScore: null, awayScore: null },
    ], [
      { id: 1, game_no: 1, source_popup_id: 49, source_game_no: 1, home_alih_team_score: null, away_alih_team_score: null, game_status: 'Scheduled' },
      { id: 2, game_no: 2, source_popup_id: 49, source_game_no: 2, home_alih_team_score: null, away_alih_team_score: null, game_status: 'Scheduled' },
    ], { sourcePopupId: 49, expectedGameCount: 2 });
  assert.deepEqual(updates, [{
      id: 1,
      gameNo: 1,
      sourceGameNo: 1,
      payload: { home_alih_team_score: 3, away_alih_team_score: 2, game_status: 'Game Finished' },
  }]);
});
