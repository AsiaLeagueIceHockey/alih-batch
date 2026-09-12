const cheerio = require('cheerio');

const GAME_SHEET_TEAM_NAMES = {
  'HL ANYANG': ['HL ANYANG ICE HOCKEY CLUB', 'HL ANYANG'],
  EAGLES: ['RED EAGLES HOKKAIDO', 'EAGLES'],
  FREEBLADES: ['TOHOKU FREEBLADES', 'FREEBLADES'],
  GRITS: ['YOKOHAMA GRITS', 'GRITS'],
  ICEBUCKS: ['NIKKO ICEBUCKS', 'ICEBUCKS'],
  STARS: ['STARS KOBE', 'STARS'],
};

const normalize = (value) => (value || '').replace(/\s+/g, ' ').trim();

function tableValue($, label) {
  const cell = $('table.sheet2 td').filter((_, element) => normalize($(element).text()) === label).first();
  return cell.length ? normalize(cell.next('td').text()) : '';
}

function teamFromHeading($, prefix) {
  const header = $('td.no').filter((_, element) => normalize($(element).text()).startsWith(prefix)).first();
  return normalize(header.find('b').first().text());
}

function expectedTeamMatches(actual, canonicalName) {
  return (GAME_SHEET_TEAM_NAMES[canonicalName] || []).includes(actual);
}

function validateGameSheetHtml(html, {
  targetSeason,
  sourceGameNo,
  homeTeam,
  awayTeam,
} = {}) {
  if (!/^\d{4}-\d{2}$/.test(targetSeason || '')) {
    throw new Error('TARGET_SEASON must be an explicit YYYY-YY value');
  }
  if (!Number.isInteger(sourceGameNo) || sourceGameNo <= 0) {
    throw new Error('sourceGameNo must be a positive integer');
  }
  const $ = cheerio.load(html);
  const body = normalize($('body').text());
  if (!body.includes('OFFICIAL GAME SHEET')) {
    throw new Error('Not an official game sheet');
  }

  const [startYear, shortEndYear] = targetSeason.split('-');
  const expectedSeasonText = `${startYear}-20${shortEndYear}`;
  const event = tableValue($, 'Event');
  if (!event.includes(expectedSeasonText)) {
    throw new Error(`Unexpected game-sheet season: ${event || '(empty)'}`);
  }

  const gameNo = Number(tableValue($, 'Game No.:'));
  if (gameNo !== sourceGameNo) {
    throw new Error(`Game-sheet number mismatch: expected ${sourceGameNo}, received ${gameNo || '(empty)'}`);
  }

  const home = teamFromHeading($, 'Home Team');
  const away = teamFromHeading($, 'Visitor Team');
  if (!expectedTeamMatches(home, homeTeam) || !expectedTeamMatches(away, awayTeam)) {
    throw new Error(`Game-sheet teams mismatch: ${home || '(empty)'} vs ${away || '(empty)'}`);
  }

  const requiredTables = [
    ['Home Team', $('td.no').filter((_, element) => normalize($(element).text()).startsWith('Home Team')).closest('table.sheet2')],
    ['Visitor Team', $('td.no').filter((_, element) => normalize($(element).text()).startsWith('Visitor Team')).closest('table.sheet2')],
    ['Game Summary', $('td').filter((_, element) => normalize($(element).text()) === 'Game Summary').closest('table.sheet2')],
    ['Saves', $('td').filter((_, element) => normalize($(element).text()) === 'Saves').closest('table.sheet2')],
    ['Goalkeeper Records', $('td').filter((_, element) => normalize($(element).text()) === 'Goalkeeper Records').closest('table.sheet2')],
  ];
  const missing = requiredTables.filter(([, table]) => !table.length).map(([name]) => name);
  if (missing.length) {
    throw new Error(`Incomplete game sheet: missing ${missing.join(', ')}`);
  }

  const end = tableValue($, 'End of game:');
  return {
    event,
    gameNo,
    home,
    away,
    isComplete: Boolean(end),
    venue: tableValue($, 'Venue'),
    spectators: tableValue($, 'Spectators:'),
  };
}

module.exports = { validateGameSheetHtml };
