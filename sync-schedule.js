const { createClient } = require('@supabase/supabase-js');
const axios = require('axios');
const cheerio = require('cheerio');
const iconv = require('iconv-lite');

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_KEY
);

const POPUP_CONFIGS = [
  { popupId: 47, seasonPhase: 'regular' },
  { popupId: 48, seasonPhase: 'playoff' },
];

const SOURCE_TEAM_MAP = {
  'HL ANYANG': 'HL ANYANG',
  'HL ANYANG ICE HOCKEY CLUB': 'HL ANYANG',
  'EAGLES': 'EAGLES',
  'RED EAGLES HOKKAIDO': 'EAGLES',
  'FREEBLADES': 'FREEBLADES',
  'TOHOKU FREEBLADES': 'FREEBLADES',
  'ICEBUCKS': 'ICEBUCKS',
  'NIKKO ICEBUCKS': 'ICEBUCKS',
  'GRITS': 'GRITS',
  'YOKOHAMA GRITS': 'GRITS',
  'STARS': 'STARS',
  'STARS KOBE': 'STARS',
};

const MONTH_MAP = {
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

function normalizeWhitespace(text) {
  return (text || '').replace(/\s+/g, ' ').trim();
}

function parseSeasonYears(title) {
  const match = title.match(/(\d{4})-(\d{4})/);
  if (!match) {
    throw new Error(`Could not parse season years from title: ${title}`);
  }
  return {
    startYear: Number(match[1]),
    endYear: Number(match[2]),
  };
}

function resolveSeasonYear(monthNumber, years, popupId) {
  if (popupId === 48) {
    return years.endYear;
  }
  return monthNumber >= 9 ? years.startYear : years.endYear;
}

function parseScore(scoreText) {
  const normalized = normalizeWhitespace(scoreText);
  const match = normalized.match(/(\d+)\s*-\s*(\d+)/);
  if (!match) {
    return { homeScore: null, awayScore: null };
  }
  return {
    homeScore: Number(match[1]),
    awayScore: Number(match[2]),
  };
}

function parseMatchAt(year, month, day, timeText) {
  const [hour, minute] = timeText.split(':').map(Number);
  const monthString = String(month).padStart(2, '0');
  const dayString = String(day).padStart(2, '0');
  const hourString = String(hour).padStart(2, '0');
  const minuteString = String(minute).padStart(2, '0');
  return `${year}-${monthString}-${dayString}T${hourString}:${minuteString}:00+09:00`;
}

async function fetchScoresPage(popupId) {
  const url = `https://www.alhockey.com/popup/${popupId}/scores.html`;
  const response = await axios.get(url, { responseType: 'arraybuffer' });
  const html = iconv.decode(response.data, 'Shift_JIS');
  return cheerio.load(html);
}

function parseScoresPage($, popupId, seasonPhase) {
  const title = normalizeWhitespace($('title').text());
  const years = parseSeasonYears(title);
  const rows = [];

  $('span.black15b').each((_, span) => {
    const monthLabel = normalizeWhitespace($(span).text());
    const monthNumber = MONTH_MAP[monthLabel.toLowerCase()];
    if (!monthNumber) {
      return;
    }

    const table = $(span).nextAll('table').filter((__, candidate) => {
      return $(candidate).find('th').filter((___, th) => normalizeWhitespace($(th).text()) === 'Game No.').length > 0;
    }).first();

    if (!table.length) {
      throw new Error(`Could not locate scores table for month: ${monthLabel}`);
    }

    const year = resolveSeasonYear(monthNumber, years, popupId);

    let currentDay = null;

    table.find('tr').slice(1).each((__, row) => {
      const cells = $(row).find('td');
      if (!cells.length) return;

      let offset = 0;
      if (cells.length === 10) {
        currentDay = Number(normalizeWhitespace(cells.eq(0).text()));
        offset = 2;
      } else if (cells.length === 8) {
        offset = 0;
      } else {
        return;
      }

      if (!currentDay) {
        throw new Error(`Row missing current day context in popup ${popupId}`);
      }

      const officialGameNo = Number(normalizeWhitespace(cells.eq(offset).text()));
      const homeSourceName = normalizeWhitespace(cells.eq(offset + 1).text());
      const scoreText = normalizeWhitespace(cells.eq(offset + 2).text());
      const awaySourceName = normalizeWhitespace(cells.eq(offset + 3).text());
      const seriesText = normalizeWhitespace(cells.eq(offset + 4).text());
      const place = normalizeWhitespace(cells.eq(offset + 5).text());
      const time = normalizeWhitespace(cells.eq(offset + 6).text());
      const gameSheetHref = cells.eq(offset + 7).find('a').attr('href') || null;

      if (!officialGameNo || !homeSourceName || !awaySourceName || !time) {
        return;
      }

      const mappedHomeName = SOURCE_TEAM_MAP[homeSourceName];
      const mappedAwayName = SOURCE_TEAM_MAP[awaySourceName];
      if (!mappedHomeName || !mappedAwayName) {
        throw new Error(`Unknown team mapping in popup ${popupId}: ${homeSourceName} vs ${awaySourceName}`);
      }

      const { homeScore, awayScore } = parseScore(scoreText);

      rows.push({
        popupId,
        seasonPhase,
        officialGameNo,
        homeSourceName,
        awaySourceName,
        mappedHomeName,
        mappedAwayName,
        matchAt: parseMatchAt(year, monthNumber, currentDay, time),
        matchPlace: place,
        homeScore,
        awayScore,
        gameStatus: homeScore !== null && awayScore !== null ? 'Game Finished' : 'Scheduled',
        sourceGameSheetUrl: gameSheetHref ? `https://www.alhockey.com${gameSheetHref}` : null,
        seriesText: seriesText || null,
      });
    });
  });

  return rows;
}

async function getTeamIdMap() {
  const { data, error } = await supabase
    .from('alih_teams')
    .select('id, english_name');

  if (error) {
    throw new Error(`Failed to fetch teams: ${error.message}`);
  }

  return new Map(data.map(team => [team.english_name, team.id]));
}

async function getExistingSchedules() {
  const { data, error } = await supabase
    .from('alih_schedule')
    .select('id, game_no, home_alih_team_id, away_alih_team_id, match_at, source_popup_id, source_game_no, season_phase, home_alih_team_score, away_alih_team_score, game_status')
    .order('game_no', { ascending: true });

  if (error) {
    throw new Error(`Failed to fetch schedule rows: ${error.message}`);
  }

  return data || [];
}

function isSameMatchTime(left, right) {
  return Math.abs(new Date(left).getTime() - new Date(right).getTime()) < 60 * 1000;
}

function findExistingSchedule(existingSchedules, parsedRow, homeTeamId, awayTeamId) {
  return existingSchedules.find((schedule) => {
    if (
      schedule.source_popup_id === parsedRow.popupId &&
      schedule.source_game_no === parsedRow.officialGameNo
    ) {
      return true;
    }

    return (
      schedule.home_alih_team_id === homeTeamId &&
      schedule.away_alih_team_id === awayTeamId &&
      isSameMatchTime(schedule.match_at, parsedRow.matchAt)
    );
  });
}

function buildUpdatePayload(parsedRow, homeTeamId, awayTeamId, existingRow) {
  const payload = {
    home_alih_team_id: homeTeamId,
    away_alih_team_id: awayTeamId,
    match_at: parsedRow.matchAt,
    match_place: parsedRow.matchPlace,
    source_popup_id: parsedRow.popupId,
    source_game_no: parsedRow.officialGameNo,
    season_phase: parsedRow.seasonPhase,
  };

  if (parsedRow.homeScore !== null && parsedRow.awayScore !== null) {
    payload.home_alih_team_score = parsedRow.homeScore;
    payload.away_alih_team_score = parsedRow.awayScore;
    payload.game_status = 'Game Finished';
  } else if (!existingRow || !existingRow.game_status || existingRow.game_status === 'Scheduled') {
    payload.game_status = 'Scheduled';
  }

  return payload;
}

async function syncSchedules() {
  console.log(`[${new Date().toISOString()}] Starting official ALH schedule sync...`);

  const teamIdMap = await getTeamIdMap();
  const existingSchedules = await getExistingSchedules();
  let nextInternalGameNo = existingSchedules.reduce((max, row) => Math.max(max, row.game_no || 0), 0);

  for (const config of POPUP_CONFIGS) {
    console.log(`[SYNC] Loading popup/${config.popupId}/scores.html (${config.seasonPhase})`);
    const $ = await fetchScoresPage(config.popupId);
    const parsedRows = parseScoresPage($, config.popupId, config.seasonPhase);

    console.log(`[SYNC] Parsed ${parsedRows.length} rows from popup/${config.popupId}`);

    for (const parsedRow of parsedRows) {
      const homeTeamId = teamIdMap.get(parsedRow.mappedHomeName);
      const awayTeamId = teamIdMap.get(parsedRow.mappedAwayName);

      if (!homeTeamId || !awayTeamId) {
        throw new Error(
          `Missing team IDs for ${parsedRow.mappedHomeName} vs ${parsedRow.mappedAwayName}`
        );
      }

      const existingRow = findExistingSchedule(existingSchedules, parsedRow, homeTeamId, awayTeamId);
      const payload = buildUpdatePayload(parsedRow, homeTeamId, awayTeamId, existingRow);

      if (existingRow) {
        const { error } = await supabase
          .from('alih_schedule')
          .update(payload)
          .eq('id', existingRow.id);

        if (error) {
          throw new Error(
            `Failed to update schedule id=${existingRow.id} for popup ${parsedRow.popupId} game ${parsedRow.officialGameNo}: ${error.message}`
          );
        }

        Object.assign(existingRow, payload);
        console.log(
          `[UPDATE] internal=${existingRow.game_no} <- popup/${parsedRow.popupId} game ${parsedRow.officialGameNo}`
        );
        continue;
      }

      nextInternalGameNo += 1;
      const insertPayload = {
        game_no: nextInternalGameNo,
        ...payload,
      };

      const { data, error } = await supabase
        .from('alih_schedule')
        .insert(insertPayload)
        .select('id, game_no')
        .single();

      if (error) {
        throw new Error(
          `Failed to insert popup ${parsedRow.popupId} game ${parsedRow.officialGameNo}: ${error.message}`
        );
      }

      existingSchedules.push({
        id: data.id,
        game_no: data.game_no,
        ...insertPayload,
      });

      console.log(
        `[INSERT] internal=${data.game_no} <- popup/${parsedRow.popupId} game ${parsedRow.officialGameNo}`
      );
    }
  }

  console.log('[DONE] Official ALH schedule sync completed.');
}

syncSchedules().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
