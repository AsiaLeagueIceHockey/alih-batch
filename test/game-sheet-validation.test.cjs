const assert = require('node:assert/strict');
const test = require('node:test');
const { validateGameSheetHtml } = require('../lib/game-sheet-validation');

const fixture = `
<html><body>
  <h1>OFFICIAL GAME SHEET</h1>
  <table class="sheet2"><tr>
    <td>Event</td><td>Asia League Ice Hockey 2026-2027 Regular</td>
    <td>Venue</td><td>Tomakomai/Japan</td>
    <td>Spectators:</td><td>1,000</td>
    <td>Game No.:</td><td>1</td>
  </tr></table>
  <table class="sheet2"><tr><td class="no">Home Team(A) <b>RED EAGLES HOKKAIDO</b></td></tr></table>
  <table class="sheet2"><tr><td class="no">Visitor Team(B) <b>NIKKO ICEBUCKS</b></td></tr></table>
  <table class="sheet2"><tr><td>Game Summary</td></tr></table>
  <table class="sheet2"><tr><td>Saves</td></tr></table>
  <table class="sheet2"><tr><td>Goalkeeper Records</td></tr></table>
  <table class="sheet2"><tr><td>End of game:</td><td>17:31</td></tr></table>
</body></html>`;

const expected = {
  targetSeason: '2026-27',
  sourceGameNo: 1,
  homeTeam: 'EAGLES',
  awayTeam: 'ICEBUCKS',
};

test('accepts a complete official game sheet with matching identity', () => {
  const result = validateGameSheetHtml(fixture, expected);
  assert.equal(result.isComplete, true);
  assert.equal(result.venue, 'Tomakomai/Japan');
  assert.equal(result.spectators, '1,000');
});

test('fails closed for a different game number', () => {
  assert.throws(() => validateGameSheetHtml(fixture, { ...expected, sourceGameNo: 2 }), /number mismatch/);
});

test('fails closed for a different team', () => {
  assert.throws(() => validateGameSheetHtml(fixture, { ...expected, awayTeam: 'STARS' }), /teams mismatch/);
});

test('marks an otherwise valid but incomplete game as not final', () => {
  const result = validateGameSheetHtml(fixture.replace('<td>End of game:</td><td>17:31</td>', '<td>End of game:</td><td></td>'), expected);
  assert.equal(result.isComplete, false);
});
