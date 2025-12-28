"""
주간 기록(Weekly Stats) 및 순위표(Standings) 캡처 및 Slack 알림 스크립트

매주 일요일 저녁 10시(KST) GitHub Actions에서 실행되어:
1. Weekly Stats 페이지 캡처
2. Standings 페이지 캡처
3. 지난 주 경기 결과 및 현재 순위 조회
4. AI 멘트 생성
5. Slack으로 알림 전송
"""

import os
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from supabase import create_client, Client
from groq import Groq
import requests

# --- 환경변수 ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# --- Supabase 클라이언트 ---
supabase: Client = None

def init_supabase():
    global supabase
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise EnvironmentError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# =============================================================================
# 1. Supabase 데이터 조회
# =============================================================================

def get_team_info() -> dict:
    """
    alih_teams에서 팀 정보 조회
    Returns: {team_id: {'name': 한국어명, 'english_name': 영어명}}
    """
    response = supabase.table('alih_teams') \
        .select('id, name, english_name') \
        .execute()
    
    return {team['id']: team for team in response.data}


def get_standings_info() -> dict:
    """
    alih_standings에서 순위 정보 조회
    Returns: {team_id: {'rank': rank, 'games_played': gp, 'points': points, 'wins': w, ...}}
    """
    response = supabase.table('alih_standings') \
        .select('*') \
        .order('rank') \
        .execute()
    
    return {s['team_id']: s for s in response.data}


def get_weekly_results() -> list:
    """
    지난 7일간(오늘 포함) 완료된 경기 조회
    KST 기준
    """
    now_kst = datetime.utcnow() + timedelta(hours=9)
    today_end = now_kst.replace(hour=23, minute=59, second=59, microsecond=999999)
    week_start = (now_kst - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    response = supabase.table('alih_schedule') \
        .select('id, game_no, match_at, home_alih_team_id, away_alih_team_id, home_alih_team_score, away_alih_team_score') \
        .gte('match_at', week_start.isoformat()) \
        .lte('match_at', today_end.isoformat()) \
        .order('match_at') \
        .execute()
    
    # 점수가 있는(완료된) 경기만 필터링
    finished_matches = [m for m in response.data if m.get('home_alih_team_score') is not None]
    
    return finished_matches


# =============================================================================
# 2. 캡처 함수
# =============================================================================

def capture_page(url: str, filename: str) -> str:
    """
    지정된 URL 캡처
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1080, 'height': 1350},
            device_scale_factor=2,
            timezone_id='Asia/Seoul'
        )
        page = context.new_page()
        
        print(f"📡 캡처 중: {url}")
        page.goto(url)
        page.wait_for_timeout(5000)  # 로딩 대기
        
        page.screenshot(path=filename)
        print(f"✅ 저장 완료: {filename}")
        
        browser.close()
        return filename

def capture_weekly_stats() -> str:
    return capture_page("https://alhockey.fans/instagram/weekly-stats", "weekly_stats.png")

def capture_standings() -> str:
    return capture_page("https://alhockey.fans/instagram/standings", "standings.png")


# =============================================================================
# 3. AI 멘트 생성 (Groq)
# =============================================================================

def format_weekly_results(matches: list, team_info: dict) -> str:
    """지난 주 경기 결과 포맷"""
    lines = []
    for match in matches:
        home_id = match['home_alih_team_id']
        away_id = match['away_alih_team_id']
        home_name = team_info.get(home_id, {}).get('name', 'Unknown')
        away_name = team_info.get(away_id, {}).get('name', 'Unknown')
        home_score = match.get('home_alih_team_score', 0)
        away_score = match.get('away_alih_team_score', 0)
        
        # 날짜
        match_dt = datetime.fromisoformat(match['match_at'].replace('Z', '+00:00')) + timedelta(hours=9)
        date_str = match_dt.strftime('%m/%d')
        
        lines.append(f"- {date_str} {home_name} {home_score}:{away_score} {away_name}")
    
    if not lines:
        return "경기 없음"
    return "\n".join(lines)


def format_standings_for_prompt(team_info: dict, standings: dict) -> str:
    """순위표 포맷 (상세)"""
    sorted_standings = sorted(standings.values(), key=lambda x: x.get('rank', 99))
    
    lines = []
    for s in sorted_standings:
        team_id = s['team_id']
        name = team_info.get(team_id, {}).get('name', 'Unknown')
        rank = s.get('rank', '?')
        points = s.get('points', 0)
        gp = s.get('games_played', 0)
        
        lines.append(f"{rank}위 {name} (승점 {points}, {gp}경기)")
    
    return "\n".join(lines)


def generate_weekly_caption(matches: list, team_info: dict, standings: dict) -> str:
    """Groq AI로 주간 결산 멘트 생성"""
    if not GROQ_API_KEY:
        return "이번 주 아시아리그 주간 기록과 순위표입니다! 🏒 #아시아리그"
    
    client = Groq(api_key=GROQ_API_KEY)
    
    weekly_results_text = format_weekly_results(matches, team_info)
    standings_text = format_standings_for_prompt(team_info, standings)
    date_info = (datetime.utcnow() + timedelta(hours=9)).strftime('%m월 %d일')
    
    example = """[12월 3주차 아시아리그 주간 결산] 🏒
    
이번 주, 리그 판도가 다시 한번 요동쳤습니다! 🔥

📊 순위 체크
HL 안양이 2연승을 거두며 선두 자리를 굳건히 지켰습니다. 반면, 레드이글스는 원정에서 뼈아픈 1패를 추가하며 주춤한 모습이네요. 중위권 싸움도 치열합니다!

🌟 Weekly Highlights
이번 주 가장 뜨거웠던 팀은 단연 닛코 아이스벅스! 공격력이 폭발하며 주간 최다 득점을 기록했습니다.

치열해지는 순위 경쟁, 다음 주 매치업도 기대해주세요!
상세 기록은 👉 @alhockey_fans 프로필 링크에서

#아시아리그아이스하키 #아시아리그 #HL안양 #레드이글스"""
    
    prompt = f"""당신은 아시아리그 아이스하키 인스타그램 계정 운영자입니다.
이번 주 경기 결과와 현재 순위표를 바탕으로 '주간 결산(Weekly Review)' 게시물 멘트를 작성해주세요.
이미지로는 '주간 개인 기록(Weekly Stats)'과 '순위표(Standings)' 이미지가 함께 올라갑니다.

[팀 정보]
{str(team_info)}

[지난 주 경기 결과]
{weekly_results_text}

[현재 순위표]
{standings_text}

[오늘 날짜]
{date_info}

[작성 예시]
{example}

[요구사항]
1. 이번 주 경기 흐름과 현재 순위 상황을 요약해서 흥미롭게 써주세요.
2. 특정 팀이 연승을 했거나 순위 변동이 컸다면 언급해주세요.
3. '주간 개인 기록'에 대한 언급도 가볍게 해주세요 (세부 데이터는 없으므로 "이번 주 맹활약한 선수는 누구일까요?" 같은 호기심 유발 스타일로).
4. 이모지 적극 활용, 한국어 자연스럽게.
5. 마지막에 @alhockey_fans 및 해시태그 포함.
6. 팀 이름은 공식 한국어 명칭 사용.

멘트를 작성해주세요."""

    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq API 에러: {e}")
        return "이번 주 아시아리그 주간 기록과 순위표입니다! 🏒"


# =============================================================================
# 4. Slack 전송 (capture.py 재사용 및 간소화)
# =============================================================================

def clean_markdown(text: str) -> str:
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    return text

def upload_image_to_supabase(file_path: str) -> str | None:
    try:
        bucket_name = "instagram-captures"
        file_name = os.path.basename(file_path)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        storage_path = f"weekly_{timestamp}_{file_name}"
        
        with open(file_path, 'rb') as f:
            file_data = f.read()
        
        supabase.storage.from_(bucket_name).upload(
            storage_path,
            file_data,
            file_options={"content-type": "image/png"}
        )
        return supabase.storage.from_(bucket_name).get_public_url(storage_path)
    except Exception as e:
        print(f"❌ 업로드 실패: {e}")
        return None

def send_to_slack(image_paths: list, caption: str):
    if not SLACK_WEBHOOK_URL:
        print("⚠️ SLACK_WEBHOOK_URL 미설정")
        return
    
    clean_caption = clean_markdown(caption)
    image_urls = []
    for path in image_paths:
        url = upload_image_to_supabase(path)
        if url: image_urls.append(url)
    
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📊 Weekly Update", "emoji": True}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{clean_caption}```"}
        },
        {"type": "divider"}
    ]
    
    labels = ["Weekly Stats", "Standings"]
    for i, url in enumerate(image_urls):
        alt = labels[i] if i < len(labels) else f"Image {i+1}"
        blocks.append({
            "type": "image",
            "image_url": url,
            "alt_text": alt,
            "title": {"type": "plain_text", "text": alt}
        })
    
    requests.post(SLACK_WEBHOOK_URL, json={"blocks": blocks})
    print("✅ Slack 전송 완료")


# =============================================================================
# 5. 메인
# =============================================================================

def main():
    print(f"[{datetime.now().isoformat()}] 🚀 주간 통계 캡처 시작")
    init_supabase()
    
    # 캡처
    images = []
    try:
        stats_img = capture_weekly_stats()
        images.append(stats_img)
    except Exception as e:
        print(f"❌ Weekly Stats 캡처 실패: {e}")
        
    try:
        standings_img = capture_standings()
        images.append(standings_img)
    except Exception as e:
        print(f"❌ Standings 캡처 실패: {e}")
    
    if not images:
        print("캡처된 이미지 없음. 종료.")
        return

    # 데이터 조회 및 AI 멘트
    team_info = get_team_info()
    standings = get_standings_info()
    weekly_matches = get_weekly_results()
    
    caption = generate_weekly_caption(weekly_matches, team_info, standings)
    print(f"\n📝 생성된 멘트:\n{caption[:200]}...")
    
    # Slack 전송
    send_to_slack(images, caption)
    print("✅ 모든 작업 완료")

if __name__ == "__main__":
    main()
