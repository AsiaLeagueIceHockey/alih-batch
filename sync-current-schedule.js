const { createClient } = require('@supabase/supabase-js');
const cheerio = require('cheerio');

const season = process.env.TARGET_SEASON;
const dryRun = process.env.DRY_RUN !== 'false';
const allowWrite = process.env.ALLOW_WRITE === 'true';
const startYear = season ? Number(season.slice(0, 4)) : NaN;

if (!season || !/^\d{4}-\d{2}$/.test(season) || !Number.isInteger(startYear)) {
  throw new Error('TARGET_SEASON must be an explicit YYYY-YY value');
}
if (!dryRun && !allowWrite) {
  throw new Error('Refusing DB write without ALLOW_WRITE=true');
}

const sourceTeams = {
  'レッドイーグルス北海道': 'EAGLES',
  'H.C.栃木日光アイスバックス': 'ICEBUCKS',
  '横浜GRITS': 'GRITS',
  'スターズ神戸': 'STARS',
  'HLアニャンアイスホッケークラブ': 'HL ANYANG',
  '東北フリーブレイズ': 'FREEBLADES',
};

const venues = {
  'nepiaアイスアリーナ': 'Tomakomai',
  'HLアニャンアイスリンク': 'Anyang',
  '日光霧降アイスアリーナ': 'Nikko',
  'FLAT HACHINOHE': 'Hachinohe',
  'KOSÉ新横浜スケートセンター': 'Shinyokohama',
  '月寒体育館': 'Sapporo',
  '尼崎スポーツの森 アイススケートリンク': 'Amagasaki',
  '尼崎スポーツの森　アイススケートリンク': 'Amagasaki',
  '神戸市立ポートアイランドスポーツセンター': 'Kobe',
  'ダイドードリンコアイスアリーナ': 'Nishitokyo',
  'ユタカアイスアリーナくしろ': 'Kushiro',
  '小瀬スポーツ公園アイスアリーナ': 'Kofu',
};

async function scrapeMonth(year, month, teamIds) {
  const url = `https://asiaicehockey.com/schedule/${year}/${String(month).padStart(2, '0')}`;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  const $ = cheerio.load(await response.text());
  const games = [];

  $('h5').each((_, heading) => {
    const dateMatch = $(heading).text().match(/(\d+)月(\d+)日/);
    if (!dateMatch) return;
    const date = `${year}-${dateMatch[1].padStart(2, '0')}-${dateMatch[2].padStart(2, '0')}`;

    $(heading).next('div.uk-grid-match').find('table.alh-table.schedule').each((__, table) => {
      const element = $(table);
      const time = element.find('tbody tr:nth-child(1) td:nth-child(1)').text().trim();
      const homeName = element.find('tbody tr:nth-child(1) td:nth-child(2)').text().trim();
      const awayName = element.find('tbody tr:nth-child(2) td:nth-child(1)').text().trim();
      const sourceUrl = element.closest('a').attr('href') || '';
      let venue = element.find('tbody tr:nth-child(4) td:nth-child(2)').text().trim()
        || element.find('tbody tr:nth-child(3) td:nth-child(2)').text().trim();
      const homeTeamId = teamIds.get(sourceTeams[homeName]);
      const awayTeamId = teamIds.get(sourceTeams[awayName]);

      if (!time || !homeTeamId || !awayTeamId || !/^https:\/\/asiaicehockey\.com\/score\/\d+$/.test(sourceUrl)) {
        throw new Error(`Unrecognized schedule row on ${date}: ${homeName} vs ${awayName}, ${sourceUrl}`);
      }

      venue = venues[venue] || venue;
      games.push({
        match_at: `${date}T${time}:00+09:00`,
        match_place: venue,
        home_alih_team_id: homeTeamId,
        away_alih_team_id: awayTeamId,
        score_url: sourceUrl,
      });
    });
  });
  return games;
}

async function main() {
  if (!process.env.SUPABASE_URL || !process.env.SUPABASE_SERVICE_KEY) {
    throw new Error('SUPABASE_URL and SUPABASE_SERVICE_KEY are required');
  }
  const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_KEY);
  const { data: teams, error: teamError } = await supabase.from('alih_teams').select('id, english_name');
  if (teamError) throw teamError;
  const teamIds = new Map(teams.map(team => [team.english_name, team.id]));
  const months = [9, 10, 11, 12].map(month => [startYear, month])
    .concat([1, 2, 3, 4].map(month => [startYear + 1, month]));
  const games = (await Promise.all(months.map(([year, month]) => scrapeMonth(year, month, teamIds))))
    .flat()
    .sort((a, b) => new Date(a.match_at) - new Date(b.match_at) || a.score_url.localeCompare(b.score_url));

  if (games.length !== 120 || new Set(games.map(game => game.score_url)).size !== 120) {
    throw new Error(`Expected 120 unique official games, received ${games.length}`);
  }

  const { data: existing, error: scheduleError } = await supabase
    .from('alih_schedule')
    .select('id, game_no, game_status, match_at, match_place, home_alih_team_id, away_alih_team_id, score_url')
    .eq('season', season)
    .order('game_no');
  if (scheduleError) throw scheduleError;
  if (existing.length !== 120) throw new Error(`Expected 120 ${season} DB rows, received ${existing.length}`);

  const matchKey = (game) => [
    new Date(game.match_at).toISOString(),
    game.home_alih_team_id,
    game.away_alih_team_id,
  ].join('|');
  const existingByKey = new Map();
  for (const row of existing) {
    const key = matchKey(row);
    if (existingByKey.has(key)) throw new Error(`Ambiguous DB schedule identity: ${key}`);
    existingByKey.set(key, row);
  }

  const sourceKeys = new Set();
  const updates = [];
  for (const source of games) {
    const key = matchKey(source);
    if (sourceKeys.has(key)) throw new Error(`Ambiguous official schedule identity: ${key}`);
    sourceKeys.add(key);
    const row = existingByKey.get(key);
    if (!row) throw new Error(`Official game has no exact DB match: ${key}`);
    if (row.game_status !== 'Scheduled') throw new Error(`Refusing to remap started game ${row.game_no}`);
    if (row.score_url && row.score_url !== source.score_url) {
      throw new Error(`Refusing to replace existing score_url for game ${row.game_no}`);
    }
    if (row.score_url !== source.score_url || row.match_place !== source.match_place) {
      updates.push({ row, source });
    }
  }
  if (sourceKeys.size !== existingByKey.size) {
    throw new Error(`Official/DB schedule identity mismatch: official=${sourceKeys.size}, db=${existingByKey.size}`);
  }

  for (const { row, source } of updates) {
    if (!dryRun) {
      const { error } = await supabase
        .from('alih_schedule')
        .update({ match_place: source.match_place, score_url: source.score_url })
        .eq('id', row.id);
      if (error) throw error;
    }
  }

  console.log(`${dryRun ? '[DRY RUN]' : '[UPDATED]'} ${updates.length} of ${existing.length} ${season} schedule rows require reconciliation`);
}

main().catch(error => {
  console.error(error.message);
  process.exit(1);
});
