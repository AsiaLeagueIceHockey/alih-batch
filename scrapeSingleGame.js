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

/**
 * [신규] 최종 스코어 문자열을 파싱하는 함수
 * "1 : 0" -> { home_score: 1, away_score: 0 }
 * 스코어가 없거나 파싱 실패 시 null 반환
 */
function parseFinalScore(scoreStr) {
  if (!scoreStr || !scoreStr.includes(':')) {
    return { home_score: null, away_score: null };
  }
  const parts = scoreStr.split(':');
  const home_score = parseInt(parts[0].trim(), 10);
  const away_score = parseInt(parts[1].trim(), 10);

  if (isNaN(home_score) || isNaN(away_score)) {
    return { home_score: null, away_score: null };
  }
  return { home_score, away_score };
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

  // 5. Supabase 'alih_game_details'에 Upsert (Insert or Update)
  const { data, error: upsertError } = await supabase
    .from('alih_game_details')
    .upsert(detailData, { onConflict: 'game_no' }); // game_no가 충돌하면 덮어쓰기

  if (upsertError) {
    throw new Error(`DB Upsert Error (alih_game_details): ${upsertError.message}`);
  }

  console.log(`[SUCCESS] Scraped and saved Game No: ${gameNoToScrape} (details)`);
  
  // --- [신규] alih_schedule에 스코어 업데이트 ---
  // 6. 'game_summary.total.score'에서 최종 스코어 파싱
  const { home_score, away_score } = parseFinalScore(game_summary.total.score);
  
  // 7. 파싱된 스코어를 `scrapeGame` 함수의 반환값으로 전달
  return { home_score, away_score };
}

// --- 메인 실행 함수 (수정됨) ---
async function main() {
  console.log(`[${new Date().toISOString()}] Starting live polling job...`);

  // 1. "진행중"인 경기를 찾기 위한 시간 정의
  const now = new Date();
  const sixHoursAgo = new Date(now.getTime() - 6 * 60 * 60 * 1000);

  try {
    // 2. alih_schedule에서 "진행중"인 경기만 쿼리
    //    [수정] 'id'(PK)를 반드시 포함해야 업데이트 가능
    const { data: ongoingGames, error: scheduleError } = await supabase
      .from('alih_schedule')
      .select('id, game_no, home_alih_team_id, away_alih_team_id')
      .gt('match_at', sixHoursAgo.toISOString()) // "6시간 전"보다 늦게 시작함
      .lt('match_at', now.toISOString());      // "지금"보다 일찍 시작함

    if (scheduleError) {
      throw new Error(`Failed to fetch schedules: ${scheduleError.message}`);
    }

    if (!ongoingGames || ongoingGames.length === 0) {
      console.log('No ongoing games found. Exiting.');
      process.exit(0); // 정상 종료
    }

    console.log(`Found ${ongoingGames.length} games to scrape: [${ongoingGames.map(g => g.game_no).join(', ')}]`);

    // 3. 찾은 모든 경기에 대해 *순차적으로* 스크래핑 실행
    //    (병렬 대신 순차 처리하여 Supabase 부하 감소 및 안정성 확보)
    for (const game of ongoingGames) {
      try {
        // [수정] scrapeGame이 스코어를 반환함
        const { home_score, away_score } = await scrapeGame(game.game_no, game);

        // 4. [신규] alih_schedule 테이블에 스코어 업데이트
        //    (스코어가 유효하게 파싱된 경우에만)
        if (home_score !== null && away_score !== null) {
          const { error: updateError } = await supabase
            .from('alih_schedule')
            .update({ 
              home_alih_team_score: home_score,
              away_alih_team_score: away_score 
            })
            .eq('id', game.id); // game_no 대신 PK인 'id'로 업데이트 (더 빠름)

          if (updateError) {
            console.error(`[WARN] Failed to update score for Game No: ${game.game_no} - ${updateError.message}`);
          } else {
            console.log(`[SUCCESS] Updated score for Game No: ${game.game_no} ( ${home_score} : ${away_score} )`);
          }
        } else {
          console.log(`[INFO] No final score found for Game No: ${game.game_no}. Skipping score update.`);
        }

      } catch (scrapeError) {
        // scrapeGame 내부에서 오류가 나도 다음 게임으로 넘어가도록 처리
        console.error(`[FAIL] Scraping failed for Game No: ${game.game_no} - ${scrapeError.message}`);
      }
    }
    
    console.log('Live polling job finished successfully.');
    process.exit(0); // 성공

  } catch (error) {
    console.error(error.message);
    process.exit(1); // 오류로 종료
  }
}

main();