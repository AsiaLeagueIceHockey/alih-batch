const { createClient } = require('@supabase/supabase-js');
const axios = require('axios');
const cheerio = require('cheerio');
const iconv = require('iconv-lite'); // Shift_JIS 디코딩 필수

// Supabase 클라이언트
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_KEY
);

// --- 헬퍼 함수 ---
function cleanText(element) {
  if (!element) return '';
  return element.text().trim();
}

function parsePlayerName(raw) {
  const match = raw.match(/^(.*?)\s?(\(C\)|\(A\))?$/);
  return {
    name: match[1] ? match[1].trim() : '',
    role: match[2] ? match[2].replace('(', '').replace(')', '') : null,
  };
}

function getPeriodFromTime(timeStr) {
  if (!timeStr || timeStr === ':') return null;
  const minutes = parseInt(timeStr.split(':')[0], 10);
  if (minutes < 20) return 1;
  if (minutes < 40) return 2;
  if (minutes < 60) return 3;
  return 4; // OVT
}

function parseRoster($, tableElement) {
  const roster = [];
  $(tableElement).find('tr').slice(3).each((i, row) => {
    const cols = $(row).find('td');
    if (cols.length !== 5) return;
    const no = parseInt(cleanText(cols.eq(0)), 10);
    if (!no) return;
    const { name, role } = parsePlayerName(cleanText(cols.eq(1)));
    roster.push({
      no: no,
      name: name,
      pos: cleanText(cols.eq(2)),
      sog: parseInt(cleanText(cols.eq(4))) || 0,
      captain_asst: role,
      played: cleanText(cols.eq(3)) === 'Y'
    });
  });
  return roster;
}

function parseGoals($, tableElement, team_id) {
  const goals = [];
  $(tableElement).find('tr').slice(3).each((i, row) => {
    const cols = $(row).find('td');
    if (cols.length < 6) return;
    const time = cleanText(cols.eq(1));
    if (time === ':') return;
    goals.push({
      period: getPeriodFromTime(time),
      time: time,
      team_id: team_id, // 득점 팀 ID
      situation: cleanText(cols.eq(5)),
      goal_no: parseInt(cleanText(cols.eq(2)), 10),
      assist1_no: parseInt(cleanText(cols.eq(3)), 10) || null,
      assist2_no: parseInt(cleanText(cols.eq(4)), 10) || null,
    });
  });
  return goals;
}

function parsePenalties($, tableElement, team_id) {
  const penalties = [];
  $(tableElement).find('tr').slice(3).each((i, row) => {
    const cols = $(row).find('td');
    if (cols.length < 6) return;
    const time = cleanText(cols.eq(0));
    if (time === ':') return;
    penalties.push({
      period: getPeriodFromTime(time),
      time: time,
      team_id: team_id, // 패널티 팀 ID
      player_no: parseInt(cleanText(cols.eq(1)), 10),
      minutes: parseInt(cleanText(cols.eq(2)), 10),
      offence: cleanText(cols.eq(3))
    });
  });
  return penalties;
}

// --- 메인 스크래핑 함수 ---
async function scrapeGame(gameNoToScrape, scheduleData) {
  const { home_alih_team_id, away_alih_team_id } = scheduleData;
  const gameSheetUrl = `https://www.alhockey.com/sheet/47/game/ogs${gameNoToScrape}.html`;
  
  console.log(`[START] Scraping Game No: ${gameNoToScrape}`);

  // 1. HTML 로드 및 Shift_JIS 디코딩
  const response = await axios.get(gameSheetUrl, { responseType: 'arraybuffer' });
  const html = iconv.decode(response.data, 'Shift_JIS');
  const $ = cheerio.load(html);

  // 2. 모든 테이블 선택 (안정적인 내용 기반 셀렉터로 수정)
  const headerTable = $('td:contains("Event")').closest('table.sheet2');
  const officialsTable = $('table.sheet2[border="1"]');

  // 홈팀 관련 테이블
  const homeRosterTable = $('td.no:contains("Home Team")').closest('table.sheet2');
  const homeGoalsTable = homeRosterTable.closest('td').next('td').find('table.sheet2');
  const homePenaltiesTable = homeRosterTable.closest('td').next('td').next('td').find('table.sheet2');
  const homeFooterTable = homeRosterTable.closest('tr').next('tr').find('table.sheet2');

  // 어웨이팀 관련 테이블
  const awayRosterTable = $('td.no:contains("Visitor Team")').closest('table.sheet2');
  const awayGoalsTable = awayRosterTable.closest('td').next('td').find('table.sheet2');
  const awayPenaltiesTable = awayRosterTable.closest('td').next('td').next('td').find('table.sheet2');
  const awayFooterTable = awayRosterTable.closest('tr').next('tr').find('table.sheet2');

  // 하단 요약 테이블
  const gameSummaryTable = $('td:contains("Game Summary")').closest('table.sheet2');
  const savesTable = $('td:contains("Saves")').closest('table.sheet2');
  const gkRecordsTable = $('td:contains("Goalkeeper Records")').closest('table.sheet2');
  const timeTable = $('td:contains("Start of game:")').closest('table.sheet2');
  

  // 3. 데이터 파싱
  
  // 3A. Game Info
  const officialsRows = officialsTable.find('tr');
  const game_info = {
    venue: cleanText(headerTable.find('td:contains("Venue")').next()),
    spectators: parseInt(cleanText(headerTable.find('td:contains("Spectators:")').next()).replace(',', '')) || 0,
    game_time: {
      start: cleanText(timeTable.find('td:contains("Start of game:")').next()),
      end: cleanText(timeTable.find('td:contains("End of game:")').next()),
    },
    timeouts: {
      home: cleanText(timeTable.find('td:contains("Timeout A:")').next()) || null,
      away: cleanText(timeTable.find('td:contains("Timeout B:")').next()) || null,
    },
    officials: {
      supervisor: cleanText(officialsRows.eq(0).find('td:contains("Game Supervisor")').next()),
      referees: [
        cleanText(officialsRows.eq(0).find('td:contains("Referee:")').first().next()),
        cleanText(officialsRows.eq(0).find('td:contains("Referee:")').last().next())
      ],
      linesmen: [
        cleanText(officialsRows.eq(2).find('td:contains("Linesman:")').first().next()),
        cleanText(officialsRows.eq(2).find('td:contains("Linesman:")').last().next())
      ]
    },
    coaches: {
      home_manager: homeFooterTable.find('td').eq(0).text().split(': ')[1]?.trim() || null,
      home_coach: homeFooterTable.find('td').eq(1).text().split(': ')[1]?.trim() || null,
      away_manager: awayFooterTable.find('td').eq(0).text().split(': ')[1]?.trim() || null,
      away_coach: awayFooterTable.find('td').eq(1).text().split(': ')[1]?.trim() || null,
    }
  };
  
  // 3B. Game Summary
  const summaryRows = gameSummaryTable.find('tr').slice(2); // 헤더 2줄 제외
  const game_summary = {
    period_1: { score: cleanText(summaryRows.eq(0).find('td').eq(1)), sog: cleanText(summaryRows.eq(0).find('td').eq(2)), pim: cleanText(summaryRows.eq(0).find('td').eq(3)), ppgf: cleanText(summaryRows.eq(0).find('td').eq(4)), shgf: cleanText(summaryRows.eq(0).find('td').eq(5)) },
    period_2: { score: cleanText(summaryRows.eq(1).find('td').eq(1)), sog: cleanText(summaryRows.eq(1).find('td').eq(2)), pim: cleanText(summaryRows.eq(1).find('td').eq(3)), ppgf: cleanText(summaryRows.eq(1).find('td').eq(4)), shgf: cleanText(summaryRows.eq(1).find('td').eq(5)) },
    period_3: { score: cleanText(summaryRows.eq(2).find('td').eq(1)), sog: cleanText(summaryRows.eq(2).find('td').eq(2)), pim: cleanText(summaryRows.eq(2).find('td').eq(3)), ppgf: cleanText(summaryRows.eq(2).find('td').eq(4)), shgf: cleanText(summaryRows.eq(2).find('td').eq(5)) },
    total: { score: cleanText(summaryRows.eq(5).find('td').eq(1)), sog: cleanText(summaryRows.eq(5).find('td').eq(2)), pim: cleanText(summaryRows.eq(5).find('td').eq(3)), ppgf: cleanText(summaryRows.eq(5).find('td').eq(4)), shgf: cleanText(summaryRows.eq(5).find('td').eq(5)) }
  };
  
  // 3C. Rosters, Goals, Penalties (순서를 3D에서 3C로 변경)
  const home_roster = parseRoster($, homeRosterTable);
  const away_roster = parseRoster($, awayRosterTable); 
  const goals = [
    ...parseGoals($, homeGoalsTable, home_alih_team_id),
    ...parseGoals($, awayGoalsTable, away_alih_team_id)
  ];
  const penalties = [
    ...parsePenalties($, homePenaltiesTable, home_alih_team_id),
    ...parsePenalties($, awayPenaltiesTable, away_alih_team_id)
  ];

  // 3D. Goalkeepers (순서를 3C에서 3D로 변경)
  const gkRows = gkRecordsTable.find('tr').slice(2);
  const savesRows = savesTable.find('tr');
  const homeGK_No = parseInt(cleanText(gkRows.eq(0).find('td').eq(0))) || null;
  const awayGK_No = parseInt(cleanText(gkRows.eq(0).find('td').eq(3))) || null;
  
  const goalkeepers = {
    home: [ { 
      no: homeGK_No, 
      name: home_roster.find(p => p.no === homeGK_No)?.name || null, // [!] OK: 이제 home_roster가 존재함
      mip: cleanText(gkRows.eq(0).find('td').eq(1)), 
      ga: parseInt(cleanText(gkRows.eq(0).find('td').eq(2))) || 0, 
      saves: parseInt(cleanText(savesRows.eq(6).find('td').eq(0))) || 0 
    } ],
    away: [ { 
      no: awayGK_No,
      name: away_roster.find(p => p.no === awayGK_No)?.name || null, // [!] OK: 이제 away_roster가 존재함
      mip: cleanText(gkRows.eq(0).find('td').eq(4)), 
      ga: parseInt(cleanText(gkRows.eq(0).find('td').eq(5))) || 0, 
      saves: parseInt(cleanText(savesRows.eq(6).find('td').eq(3))) || 0 
    } ]
  };

  // 4. DB에 삽입할 최종 객체
  const detailData = {
    game_no: parseInt(gameNoToScrape, 10),
    spectators: game_info.spectators,
    game_info: game_info,
    game_summary: game_summary,
    goalkeepers: goalkeepers,
    home_roster: home_roster,
    away_roster: away_roster,
    goals: goals,
    penalties: penalties
  };

  // 5. Supabase에 Upsert (Insert or Update)
  const { data, error: upsertError } = await supabase
    .from('alih_game_details')
    .upsert(detailData, { onConflict: 'game_no' }); // game_no가 충돌하면 덮어쓰기

  if (upsertError) {
    throw new Error(`DB Upsert Error: ${upsertError.message}`);
  }

  console.log(`[SUCCESS] Scraped and saved Game No: ${gameNoToScrape}`);
  return data;
}

// --- 메인 실행 함수 ---
async function main() {
  const gameNoToScrape = process.env.GAME_NO_TO_SCRAPE;

  if (!gameNoToScrape) {
    console.error('Error: GAME_NO_TO_SCRAPE environment variable is not set.');
    process.exit(1); // 오류로 종료
  }
  
  try {
    // 1. 득점/패널티에 팀 ID를 넣기 위해 alih_schedule에서 팀 정보를 가져옵니다.
    const { data: scheduleData, error: scheduleError } = await supabase
      .from('alih_schedule')
      .select('home_alih_team_id, away_alih_team_id')
      .eq('game_no', gameNoToScrape)
      .single(); 

    if (scheduleError || !scheduleData) {
      throw new Error(`Failed to find schedule info for game_no ${gameNoToScrape}: ${scheduleError?.message}`);
    }

    // 2. 스크래핑 및 DB 저장 실행
    await scrapeGame(gameNoToScrape, scheduleData);
    
    console.log('Manual job finished.');
    process.exit(0); // 성공

  } catch (error) {
    console.error(error.message);
    process.exit(1); // 오류로 종료
  }
}

main();