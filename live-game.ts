import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';
import * as cheerio from 'https://esm.sh/cheerio@1.0.0-rc.12';
import { corsHeaders } from '../_shared/cors.ts';

// 서비스 롤 키를 사용해 RLS를 우회하는 어드민 클라이언트 생성
const supabase = createClient(
  Deno.env.get('SUPABASE_URL')!,
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
);

// --- 헬퍼 함수 ---
function cleanText(element: cheerio.Cheerio) {
  if (!element) return '';
  return element.text().trim();
}

/**
 * 라이브 스코어 페이지 (asiaicehockey.com/score/...)를 파싱합니다.
 * 이 페이지는 Game Sheet(ogs.html)과 구조가 다릅니다.
 * * [가정]
 * 1. 라이브 스코어는 JavaScript가 아닌 HTML에 렌더링되어 있습니다.
 * 2. 스코어 테이블 <table class="alh-table report">의 빈 <td>가 채워집니다.
 * (예: <td>1</td> <td>1P</td> <td>0</td>)
 */
async function parseLiveScorePage(game: any) {
  const { id: schedule_id, game_no, home_alih_team_id, away_alih_team_id } = game;
  const liveScoreUrl = `https://asiaicehockey.com/score/${game_no + 20388}`;
  
  console.log(`[LIVE] Fetching Game No: ${game_no}`);
  
  const response = await fetch(liveScoreUrl);
  if (!response.ok) {
    throw new Error(`Failed to fetch live score page: ${response.statusText}`);
  }
  
  // 아시아리그 사이트는 charset이 명시되어 있지 않아도, 
  // Deno/cheerio가 UTF-8로 잘 파싱합니다. (Shift_JIS 불필요)
  const html = await response.text();
  const $ = cheerio.load(html);

  const scoreTable = $('table.alh-table.report');
  
  // --- 1. 스코어 파싱 (alih_schedule 업데이트용) ---
  const periodRows = scoreTable.find('tbody > tr');
  
  let home_score = 0;
  let away_score = 0;
  
  // 1P, 2P, 3P의 스코어를 찾아서 합산
  const p1_home = parseInt(cleanText(periodRows.eq(0).find('td').eq(0)), 10) || 0;
  const p1_away = parseInt(cleanText(periodRows.eq(0).find('td').eq(2)), 10) || 0;
  const p2_home = parseInt(cleanText(periodRows.eq(1).find('td').eq(0)), 10) || 0;
  const p2_away = parseInt(cleanText(periodRows.eq(1).find('td').eq(2)), 10) || 0;
  const p3_home = parseInt(cleanText(periodRows.eq(2).find('td').eq(0)), 10) || 0;
  const p3_away = parseInt(cleanText(periodRows.eq(2).find('td').eq(2)), 10) || 0;
  
  home_score = p1_home + p2_home + p3_home;
  away_score = p1_away + p2_away + p3_away;

  // OVT (연장) 스코어 합산
  const ovt_home = parseInt(cleanText(periodRows.eq(3).find('td').eq(0)), 10) || 0;
  const ovt_away = parseInt(cleanText(periodRows.eq(3).find('td').eq(2)), 10) || 0;
  home_score += ovt_home;
  away_score += ovt_away;

  // PSS (승부샷) 스코어 합산
  const pss_home = parseInt(cleanText(periodRows.eq(4).find('td').eq(0)), 10) || 0;
  const pss_away = parseInt(cleanText(periodRows.eq(4).find('td').eq(2)), 10) || 0;
  home_score += pss_home;
  away_score += pss_away;

  // --- 2. 임시 상세 데이터 생성 (alih_game_details 업데이트용) ---
  // 라이브 페이지는 상세 정보가 없으므로, 최종본과 "비슷하게" 만들되
  // 대부분의 정보는 비워두고 피리어드별 스코어만 채웁니다.
  const tempDetailData = {
    game_no: game_no,
    spectators: null, // 라이브 페이지에는 관중 정보가 없음
    game_info: {
      venue: cleanText($('p.uk-text-lighter').eq(2)).split(' ')[0] || null, // 예: "HLアニャンアイスリンク"
      coaches: null,
      timeouts: null,
      game_time: null,
      officials: null,
    },
    game_summary: { // 피리어드별 스코어만 임시 저장
      total: { score: `${home_score} : ${away_score}`, sog: null, pim: null, ppgf: null, shgf: null },
      period_1: { score: `${p1_home} : ${p1_away}`, sog: null, pim: null, ppgf: null, shgf: null },
      period_2: { score: `${p2_home} : ${p2_away}`, sog: null, pim: null, ppgf: null, shgf: null },
      period_3: { score: `${p3_home} : ${p3_away}`, sog: null, pim: null, ppgf: null, shgf: null },
    },
    goalkeepers: null, // 라이브 페이지에는 골키퍼 정보가 없음
    home_roster: null, // 라이브 페이지에는 로스터 정보가 없음
    away_roster: null,
    goals: null,       // 라이브 페이지에는 득점자 정보가 없음
    penalties: null    // 라이브 페이지에는 패널티 정보가 없음
  };
  
  // --- 3. 두 테이블을 동시에 업데이트 (Supabase 트랜잭션 사용) ---
  // Supabase는 네이티브 트랜잭션을 지원하지 않으므로, 
  // 두 개의 쿼리를 순차적으로 실행합니다.
  
  // 3A. alih_schedule 업데이트 (라이브 스코어)
  const { error: scheduleUpdateError } = await supabase
    .from('alih_schedule')
    .update({ 
      home_alih_team_score: home_score,
      away_alih_team_score: away_score 
    })
    .eq('id', schedule_id); // PK로 업데이트

  if (scheduleUpdateError) {
    throw new Error(`DB Update Error (alih_schedule): ${scheduleUpdateError.message}`);
  }
  console.log(`[SUCCESS] Updated schedule score for Game No: ${game_no} (${home_score} : ${away_score})`);

  // 3B. alih_game_details 업데이트 (임시 데이터)
  const { error: detailsUpsertError } = await supabase
    .from('alih_game_details')
    .upsert(tempDetailData, { onConflict: 'game_no' });

  if (detailsUpsertError) {
    throw new Error(`DB Upsert Error (alih_game_details): ${detailsUpsertError.message}`);
  }
  console.log(`[SUCCESS] Upserted temporary details for Game No: ${game_no}`);
}


// --- Deno Edge Function 메인 핸들러 ---
Deno.serve(async (req) => {
  // Cron으로 실행될 것이므로, HTTP 요청 본문은 무시합니다.
  console.log(`[${new Date().toISOString()}] Starting live score polling job...`);
  
  // 1. "진행중"인 경기를 찾기 위한 시간 정의
  const now = new Date();
  // 6시간 전 시간 (게임 종료 시점)
  const sixHoursAgo = new Date(now.getTime() - 6 * 60 * 60 * 1000);
  
  let ongoingGames = [];

  try {
    // 2. alih_schedule에서 "진행중"인 경기만 쿼리
    const { data, error: scheduleError } = await supabase
      .from('alih_schedule')
      .select('id, game_no, home_alih_team_id, away_alih_team_id')
      .gt('match_at', sixHoursAgo.toISOString()) // 6시간 전 이후 시작
      .lt('match_at', now.toISOString());      // 현재 시간 이전 시작

    if (scheduleError) {
      throw new Error(`Failed to fetch schedules: ${scheduleError.message}`);
    }
    
    ongoingGames = data || [];

  } catch (error) {
     return new Response(JSON.stringify({ error: error.message }), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      status: 500,
    });
  }
  
  if (ongoingGames.length === 0) {
    console.log('No ongoing games found. Exiting.');
    return new Response(JSON.stringify({ message: 'No ongoing games found.' }), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      status: 200,
    });
  }

  console.log(`Found ${ongoingGames.length} ongoing games to scrape: [${ongoingGames.map(g => g.game_no).join(', ')}]`);

  // 3. 찾은 모든 경기에 대해 순차적으로 스크래핑 실행
  const results = [];
  for (const game of ongoingGames) {
    try {
      await parseLiveScorePage(game);
      results.push({ game_no: game.game_no, status: 'success' });
    } catch (scrapeError) {
      console.error(`[FAIL] Scraping failed for Game No: ${game.game_no} - ${scrapeError.message}`);
      results.push({ game_no: game.game_no, status: 'failed', error: scrapeError.message });
    }
  }

  // 4. Cron 작업 결과 반환
  console.log('Live polling job finished successfully.');
  return new Response(JSON.stringify({ 
    message: 'Live polling job finished.',
    results: results 
  }), {
    headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    status: 200,
  });
});