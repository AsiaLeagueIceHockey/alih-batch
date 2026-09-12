const crypto = require('crypto');
const cheerio = require('cheerio');
const iconv = require('iconv-lite');

const MONTHS = {
  january: 1,
  february: 2,
  march: 3,
  april: 4,
  may: 5,
  june: 6,
  july: 7,
  august: 8,
  september: 9,
  october: 10,
  november: 11,
  december: 12,
};

const DEFAULT_TEAM_MAP = {
  'HL ANYANG': 'HL ANYANG',
  'HL ANYANG ICE HOCKEY CLUB': 'HL ANYANG',
  EAGLES: 'EAGLES',
  'RED EAGLES HOKKAIDO': 'EAGLES',
  FREEBLADES: 'FREEBLADES',
  'TOHOKU FREEBLADES': 'FREEBLADES',
  ICEBUCKS: 'ICEBUCKS',
  'NIKKO ICEBUCKS': 'ICEBUCKS',
  GRITS: 'GRITS',
  'YOKOHAMA GRITS': 'GRITS',
  STARS: 'STARS',
  'STARS KOBE': 'STARS',
};

const normalize = (value) => (value || '').replace(/\s+/g, ' ').trim();

function assertSeason(targetSeason) {
  if (!/^\d{4}-\d{2}$/.test(targetSeason || '')) {
    throw new Error('TARGET_SEASON must be an explicit YYYY-YY value');
  }
}

function expectedTitleToken(targetSeason, phase) {
  const [startYear, shortEndYear] = targetSeason.split('-');
  return `${startYear}-20${shortEndYear} / ${phase === 'playoff' ? 'Play-off' : 'Regular'}`;
}

function parseMatchAt(year, month, day, time) {
  if (!/^\d{1,2}:\d{2}$/.test(time)) {
    throw new Error(`Invalid popup start time: ${time}`);
  }
  const [hour, minute] = time.split(':').map(Number);
  if (hour > 23 || minute > 59) {
    throw new Error(`Invalid popup start time: ${time}`);
  }
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:00+09:00`;
}

function parseScore(value) {
  const match = normalize(value).match(/^(\d+)\s*-\s*(\d+)$/);
  return match
    ? { homeScore: Number(match[1]), awayScore: Number(match[2]) }
    : { homeScore: null, awayScore: null };
}

function decodePopupHtml(body) {
  return iconv.decode(Buffer.isBuffer(body) ? body : Buffer.from(body), 'shift_jis');
}

function normalizedScheduleHash(rows) {
  const stableRows = rows
    .map((row) => ({
      gameNo: row.officialGameNo,
      home: row.mappedHomeName,
      away: row.mappedAwayName,
      matchAt: new Date(row.matchAt).toISOString(),
      matchPlace: row.matchPlace,
    }))
    .sort((left, right) => left.gameNo - right.gameNo);
  return crypto.createHash('sha256').update(JSON.stringify(stableRows)).digest('hex');
}

function parsePopupScoresHtml(html, {
  targetSeason,
  popupId,
  seasonPhase = 'regular',
  expectedGameCount,
  teamMap = DEFAULT_TEAM_MAP,
  baseUrl = 'https://www.alhockey.com',
} = {}) {
  assertSeason(targetSeason);
  if (!Number.isInteger(popupId) || popupId <= 0) {
    throw new Error('SOURCE_POPUP_ID must be a positive integer');
  }
  if (!Number.isInteger(expectedGameCount) || expectedGameCount <= 0) {
    throw new Error('EXPECTED_GAME_COUNT must be a positive integer');
  }

  const $ = cheerio.load(html);
  const title = normalize($('title').text());
  const titleToken = expectedTitleToken(targetSeason, seasonPhase);
  if (!title.includes(titleToken)) {
    throw new Error(`Unexpected popup title: expected ${titleToken}, received ${title || '(empty)'}`);
  }

  const [startYear] = targetSeason.split('-').map(Number);
  const rows = [];
  const parseErrors = [];

  $('span.black15b').each((_, span) => {
    const monthLabel = normalize($(span).text());
    const month = MONTHS[monthLabel.toLowerCase()];
    if (!month) return;

    const table = $(span).nextAll('table').filter((__, candidate) => (
      $(candidate).find('th').filter((___, header) => normalize($(header).text()) === 'Game No.').length > 0
    )).first();

    if (!table.length) {
      parseErrors.push(`Missing scores table for ${monthLabel}`);
      return;
    }

    let day = null;
    const year = month >= 9 ? startYear : startYear + 1;
    table.find('tr').slice(1).each((__, tr) => {
      const cells = $(tr).find('td');
      if (!cells.length) return;

      let offset;
      if (cells.length === 10) {
        day = Number(normalize(cells.eq(0).text()));
        offset = 2;
      } else if (cells.length === 8) {
        offset = 0;
      } else {
        parseErrors.push(`Unexpected cell count ${cells.length} in ${monthLabel}`);
        return;
      }

      if (!Number.isInteger(day) || day < 1 || day > 31) {
        parseErrors.push(`Missing day context in ${monthLabel}`);
        return;
      }

      const officialGameNo = Number(normalize(cells.eq(offset).text()));
      const homeSourceName = normalize(cells.eq(offset + 1).text());
      const scoreText = normalize(cells.eq(offset + 2).text());
      const awaySourceName = normalize(cells.eq(offset + 3).text());
      const seriesText = normalize(cells.eq(offset + 4).text());
      const matchPlace = normalize(cells.eq(offset + 5).text());
      const time = normalize(cells.eq(offset + 6).text());
      const gameSheetHref = cells.eq(offset + 7).find('a').attr('href') || null;

      if (!Number.isInteger(officialGameNo) || officialGameNo <= 0 || !homeSourceName || !awaySourceName || !matchPlace || !time) {
        parseErrors.push(`Incomplete row in ${monthLabel} day ${day}`);
        return;
      }

      const mappedHomeName = teamMap[homeSourceName];
      const mappedAwayName = teamMap[awaySourceName];
      if (!mappedHomeName || !mappedAwayName) {
        parseErrors.push(`Unknown team mapping: ${homeSourceName} vs ${awaySourceName}`);
        return;
      }

      try {
        const { homeScore, awayScore } = parseScore(scoreText);
        rows.push({
          popupId,
          seasonPhase,
          officialGameNo,
          homeSourceName,
          awaySourceName,
          mappedHomeName,
          mappedAwayName,
          matchAt: parseMatchAt(year, month, day, time),
          matchPlace,
          homeScore,
          awayScore,
          gameStatus: homeScore === null ? 'Scheduled' : 'Game Finished',
          sourceGameSheetUrl: gameSheetHref ? new URL(gameSheetHref, baseUrl).toString() : null,
          seriesText: seriesText || null,
        });
      } catch (error) {
        parseErrors.push(error.message);
      }
    });
  });

  if (parseErrors.length) {
    throw new Error(`Popup parse failed: ${parseErrors.join('; ')}`);
  }
  if (rows.length !== expectedGameCount) {
    throw new Error(`Expected ${expectedGameCount} games, received ${rows.length}`);
  }

  const numbers = rows.map((row) => row.officialGameNo);
  const uniqueNumbers = new Set(numbers);
  if (uniqueNumbers.size !== expectedGameCount) {
    throw new Error(`Expected ${expectedGameCount} unique Game No values, received ${uniqueNumbers.size}`);
  }
  for (let gameNo = 1; gameNo <= expectedGameCount; gameNo += 1) {
    if (!uniqueNumbers.has(gameNo)) {
      throw new Error(`Missing official Game No ${gameNo}`);
    }
  }

  return {
    title,
    rows: rows.sort((left, right) => left.officialGameNo - right.officialGameNo),
    normalizedScheduleHash: normalizedScheduleHash(rows),
  };
}

module.exports = {
  DEFAULT_TEAM_MAP,
  decodePopupHtml,
  normalizedScheduleHash,
  parsePopupScoresHtml,
};
