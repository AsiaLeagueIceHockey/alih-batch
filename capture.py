"""
Instagram Preview/Result 캡처 및 Slack 알림 스크립트

매일 저녁 9시(KST) GitHub Actions에서 실행되어:
1. 오늘 완료된 경기 → Result 캡처 + AI 멘트
2. 내일 예정된 경기 → Preview 캡처 + AI 멘트
3. Slack으로 알림 전송
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
    Returns: {team_id: {'rank': rank, 'points': points}}
    """
    response = supabase.table('alih_standings') \
        .select('team_id, rank, points') \
        .order('rank') \
        .execute()
    
    return {s['team_id']: {'rank': s['rank'], 'points': s['points']} for s in response.data}


def get_todays_matches() -> list:
    """
    오늘 00:00 ~ 23:59 사이 경기 조회 (Result용)
    KST 기준으로 계산
    """
    # KST = UTC+9
    now_kst = datetime.utcnow() + timedelta(hours=9)
    today_start = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now_kst.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    response = supabase.table('alih_schedule') \
        .select('id, game_no, match_at, home_alih_team_id, away_alih_team_id, home_alih_team_score, away_alih_team_score') \
        .gte('match_at', today_start.isoformat()) \
        .lte('match_at', today_end.isoformat()) \
        .order('match_at') \
        .execute()
    
    return response.data


def get_tomorrows_matches() -> list:
    """
    내일 00:00 ~ 23:59 사이 경기 조회 (Preview용)
    KST 기준으로 계산
    """
    # KST = UTC+9
    now_kst = datetime.utcnow() + timedelta(hours=9)
    tomorrow = now_kst + timedelta(days=1)
    tomorrow_start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_end = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    response = supabase.table('alih_schedule') \
        .select('id, game_no, match_at, home_alih_team_id, away_alih_team_id') \
        .gte('match_at', tomorrow_start.isoformat()) \
        .lte('match_at', tomorrow_end.isoformat()) \
        .order('match_at') \
        .execute()
    
    return response.data


# =============================================================================
# 2. 캡처 함수
# =============================================================================

def capture_match_result(game_no: int) -> str:
    """
    Result 페이지 캡처
    Returns: 저장된 파일 경로
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1080, 'height': 1350},
            device_scale_factor=2,
            timezone_id='Asia/Seoul'  # KST 타임존 설정
        )
        page = context.new_page()
        
        target_url = f"https://alhockey.fans/instagram/score?game_no={game_no}"
        print(f"📡 [Result] 캡처 중: {target_url}")
        page.goto(target_url)
        page.wait_for_timeout(5000)  # 로고 등 로딩 대기
        
        file_name = f"result_{game_no}.png"
        page.screenshot(path=file_name, full_page=True)
        print(f"✅ 저장 완료: {file_name}")
        
        browser.close()
        return file_name


def capture_match_preview(game_no: int) -> str:
    """
    Preview 페이지 캡처
    Returns: 저장된 파일 경로
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1080, 'height': 1350},
            device_scale_factor=2,
            timezone_id='Asia/Seoul'  # KST 타임존 설정
        )
        page = context.new_page()
        
        target_url = f"https://alhockey.fans/instagram/preview?game_no={game_no}"
        print(f"📡 [Preview] 캡처 중: {target_url}")
        page.goto(target_url)
        page.wait_for_timeout(5000)  # 로고 등 로딩 대기
        
        file_name = f"preview_{game_no}.png"
        page.screenshot(path=file_name, full_page=True)
        print(f"✅ 저장 완료: {file_name}")
        
        browser.close()
        return file_name


# =============================================================================
# 3. AI 멘트 생성 (Groq)
# =============================================================================

def format_match_info_for_preview(matches: list, team_info: dict, standings: dict) -> str:
    """경기 정보 포맷 (Preview용)"""
    lines = []
    for i, match in enumerate(matches, 1):
        home_id = match['home_alih_team_id']
        away_id = match['away_alih_team_id']
        
        home_name = team_info.get(home_id, {}).get('name', 'Unknown')
        away_name = team_info.get(away_id, {}).get('name', 'Unknown')
        home_standing = standings.get(home_id, {})
        away_standing = standings.get(away_id, {})
        home_rank = home_standing.get('rank', '?')
        away_rank = away_standing.get('rank', '?')
        home_pts = home_standing.get('points', 0)
        away_pts = away_standing.get('points', 0)
        
        match_time = match['match_at']
        if match_time:
            try:
                dt = datetime.fromisoformat(match_time.replace('Z', '+00:00'))
                time_str = dt.strftime('%H:%M')
            except:
                time_str = ""
        else:
            time_str = ""
        
        lines.append(f"{i}. {home_name} ({home_rank}위, {home_pts}pts) vs {away_name} ({away_rank}위, {away_pts}pts) - {time_str}")
    
    return "\n".join(lines)


def format_match_info_for_result(matches: list, team_info: dict, standings: dict) -> str:
    """경기 결과 포맷 (Result용)"""
    lines = []
    for i, match in enumerate(matches, 1):
        home_id = match['home_alih_team_id']
        away_id = match['away_alih_team_id']
        
        home_name = team_info.get(home_id, {}).get('name', 'Unknown')
        away_name = team_info.get(away_id, {}).get('name', 'Unknown')
        home_score = match.get('home_alih_team_score', 0) or 0
        away_score = match.get('away_alih_team_score', 0) or 0
        
        lines.append(f"{i}. {home_name} ({home_score}) : ({away_score}) {away_name}")
    
    return "\n".join(lines)


def format_league_standings(team_info: dict, standings: dict) -> str:
    """전체 리그 순위표 포맷 (AI 컨텍스트용)"""
    # standings를 순위 순으로 정렬
    sorted_standings = sorted(standings.items(), key=lambda x: x[1].get('rank', 99))
    
    lines = []
    for team_id, standing in sorted_standings:
        team = team_info.get(team_id, {})
        team_name = team.get('name', 'Unknown')
        rank = standing.get('rank', '?')
        points = standing.get('points', 0)
        lines.append(f"{rank}위. {team_name} - {points}pts")
    
    return "\n".join(lines)


def generate_caption(matches: list, team_info: dict, standings: dict, caption_type: str) -> str:
    """
    Groq AI로 Instagram 멘트 생성
    caption_type: 'preview' | 'result'
    """
    if not GROQ_API_KEY:
        print("⚠️ GROQ_API_KEY가 설정되지 않음. 기본 멘트 반환.")
        return f"[{caption_type.upper()}] {len(matches)}개 경기"
    
    client = Groq(api_key=GROQ_API_KEY)
    
    # 팀 컨텍스트
    team_context = "\n".join([
        f"- {t['name']} (영문: {t['english_name']})" 
        for t in team_info.values()
    ])
    
    # 전체 리그 순위표
    league_standings = format_league_standings(team_info, standings)
    
    # 경기 정보
    if caption_type == 'preview':
        match_info = format_match_info_for_preview(matches, team_info, standings)
        date_info = (datetime.utcnow() + timedelta(hours=9) + timedelta(days=1)).strftime('%m월 %d일')
    else:
        match_info = format_match_info_for_result(matches, team_info, standings)
        date_info = (datetime.utcnow() + timedelta(hours=9)).strftime('%m월 %d일')
    
    # 프롬프트
    if caption_type == 'preview':
        example = """12월 2주차 아시아리그 PREVIEW 🏒

1️⃣ HL 안양 (2위) vs 닛코 아이스벅스 (3위) 👉 지난 9월 원정의 빚을 갚을 시간! 2위 수성과 선두 추격을 위한 필승의 홈 리벤지 매치 ⚔️

2️⃣ 레드이글스 홋카이도 (1위) vs 요코하마 그리츠 (4위) 👉 압도적 1위의 독주 체제 굳히기냐, 도깨비팀 그리츠의 반란이냐! 물러설 곳 없는 승부 🛡️

추운 겨울, 가장 뜨거운 열기를 느낄 수 있는 아이스하키 직관 어떠신가요? 🏟️

👇 모든 경기 일정과 실시간 기록 분석은 여기서!
@alhockey_fans 프로필 링크 클릭!

#아시아리그아이스하키 #아시아리그 #hl안양 #redeagles"""
        
        prompt = f"""당신은 아시아리그 아이스하키 인스타그램 계정 운영자입니다.
내일 예정된 경기들의 PREVIEW 멘트를 작성해주세요.

[아시아리그 팀 정보 - 반드시 이 이름들만 사용하세요]
{team_context}

[현재 리그 순위표 - 포인트 차이를 참고하여 경기 분위기를 파악하세요]
{league_standings}

[내일 경기 정보 - {date_info}]
{match_info}

[작성 예시]
{example}

[요구사항]
1. 각 경기마다 기대포인트를 흥미롭게 작성 (순위 경쟁, 포인트 차이, 홈/원정 매치업 등)
2. 팀 이름은 반드시 위 [팀 정보]에 있는 한국어 이름만 사용
3. 이모지 적극 활용
4. 마지막에 @alhockey_fans 멘션과 해시태그 포함
5. 해시태그에는 팀 영문명(소문자, 공백제거)도 포함
6. 주의: 선수 이름, 개인 기록, 부상 정보 등 제공되지 않은 정보는 절대 언급하지 마세요. 오직 위에 제공된 정보만 사용하세요.

위 예시 스타일을 참고하여 멘트를 작성해주세요."""

    else:  # result
        example = """12월 14일 일요일, 오늘의 아시아리그 결과 🏒
1, 2위 팀이 홈에서 나란히 덜미를 잡혔습니다. 순위는 카오스 속으로!

1️⃣ HL 안양 (2) : (6) 아이스벅스 👉 3피리어드에만 4득점 폭발! 🔥 아이스벅스가 안양 원정에서 귀중한 대승을 거두며 2위 자리를 맹추격합니다. 🚀

2️⃣ 레드 이글스 (4) : (5) 요코하마 그리츠 (OT) 👉 연장 접전 끝에 터진 결승골! 그리츠가 선두 레드 이글스의 발목을 제대로 잡았습니다. (오늘의 자이언트 킬링! 🗡️)

갈수록 치열해지는 순위 경쟁, 상세 기록은 프로필 링크에서 확인하세요!
@alhockey_fans

#아시아리그아이스하키 #아시아리그 #hl안양 #redeagles"""

        prompt = f"""당신은 아시아리그 아이스하키 인스타그램 계정 운영자입니다.
오늘 진행된 경기들의 RESULT 멘트를 작성해주세요.

[아시아리그 팀 정보 - 반드시 이 이름들만 사용하세요]
{team_context}

[현재 리그 순위표 - 포인트 차이를 참고하여 경기 의미를 분석하세요]
{league_standings}

[오늘 경기 결과 - {date_info}]
{match_info}

[작성 예시]
{example}

[요구사항]
1. 각 경기 결과에 대한 짧은 분석/코멘트 작성
2. 점수 차이가 크면 대승/완패, 1점차면 접전 등 표현 활용
3. 팀 이름은 반드시 위 [팀 정보]에 있는 한국어 이름만 사용
4. 이모지 적극 활용
5. 마지막에 @alhockey_fans 멘션과 해시태그 포함
6. 해시태그에는 팀 영문명(소문자, 공백제거)도 포함
7. 주의: 선수 이름, 득점자, 개인 기록 등 제공되지 않은 정보는 절대 언급하지 마세요. 오직 위에 제공된 점수와 팀 정보만 사용하세요.

위 예시 스타일을 참고하여 멘트를 작성해주세요."""

    # 프롬프트 로깅
    print(f"\n{'='*60}")
    print(f"📤 [Groq API] {caption_type.upper()} 프롬프트 전송")
    print(f"{'='*60}")
    print(prompt)
    print(f"{'='*60}\n")
    
    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq API 에러: {e}")
        return f"[{caption_type.upper()}] AI 멘트 생성 실패"


# =============================================================================
# 4. Slack 알림
# =============================================================================

def clean_markdown(text: str) -> str:
    """
    마크다운 문법 제거 (인스타그램 복붙용)
    """
    # **bold** -> bold
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    # *italic* -> italic
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    # __underline__ -> underline
    text = re.sub(r'__(.+?)__', r'\1', text)
    # _italic_ -> italic
    text = re.sub(r'_(.+?)_', r'\1', text)
    # ~~strikethrough~~ -> strikethrough
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    # `code` -> code
    text = re.sub(r'`(.+?)`', r'\1', text)
    return text


def upload_image_to_supabase(file_path: str) -> str | None:
    """
    이미지를 Supabase Storage에 업로드하고 Public URL 반환
    """
    try:
        bucket_name = "instagram-captures"
        file_name = os.path.basename(file_path)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        storage_path = f"{timestamp}_{file_name}"
        
        with open(file_path, 'rb') as f:
            file_data = f.read()
        
        # 업로드
        response = supabase.storage.from_(bucket_name).upload(
            storage_path,
            file_data,
            file_options={"content-type": "image/png"}
        )
        
        # Public URL 생성
        public_url = supabase.storage.from_(bucket_name).get_public_url(storage_path)
        print(f"✅ Supabase Storage 업로드 완료: {storage_path}")
        return public_url
        
    except Exception as e:
        print(f"❌ Supabase Storage 업로드 실패: {e}")
        return None


def send_to_slack(image_paths: list, caption: str, caption_type: str):
    """
    Slack Webhook으로 멘트 + 이미지 전송
    """
    if not SLACK_WEBHOOK_URL:
        print("⚠️ SLACK_WEBHOOK_URL이 설정되지 않음. Slack 전송 생략.")
        return
    
    emoji = "📸" if caption_type == "preview" else "🏒"
    title = "PREVIEW" if caption_type == "preview" else "RESULT"
    
    # 마크다운 제거한 깨끗한 멘트
    clean_caption = clean_markdown(caption)
    
    # 이미지를 Supabase Storage에 업로드하고 URL 수집
    image_urls = []
    for path in image_paths:
        url = upload_image_to_supabase(path)
        if url:
            image_urls.append(url)
    
    # Slack 메시지 구성
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Instagram {title}",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"```{clean_caption}```"
            }
        },
        {
            "type": "divider"
        }
    ]
    
    # 이미지들 추가
    for i, url in enumerate(image_urls):
        blocks.append({
            "type": "image",
            "image_url": url,
            "alt_text": f"{caption_type}_{i+1}"
        })
    
    payload = {"blocks": blocks}
    
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload)
        if response.status_code == 200:
            print(f"✅ Slack 전송 완료 ({caption_type})")
        else:
            print(f"❌ Slack 전송 실패: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Slack 전송 에러: {e}")


# =============================================================================
# 5. 메인 함수
# =============================================================================

def main():
    print(f"[{datetime.now().isoformat()}] 🚀 Instagram 캡처 스크립트 시작")
    
    # Supabase 초기화
    init_supabase()
    
    # 팀 정보 & 순위 정보 로드
    team_info = get_team_info()
    standings = get_standings_info()
    print(f"📊 팀 정보 로드: {len(team_info)}개 팀")
    
    # --- 오늘 경기 처리 (Result) ---
    todays_matches = get_todays_matches()
    print(f"\n📅 오늘 경기: {len(todays_matches)}개")
    
    if todays_matches:
        # 캡처
        result_images = []
        for match in todays_matches:
            game_no = match['game_no']
            try:
                image_path = capture_match_result(game_no)
                result_images.append(image_path)
            except Exception as e:
                print(f"❌ Result 캡처 실패 (game_no={game_no}): {e}")
        
        # AI 멘트 생성
        if result_images:
            result_caption = generate_caption(todays_matches, team_info, standings, 'result')
            print(f"\n📝 Result 멘트:\n{result_caption[:200]}...")
            
            # Slack 전송
            send_to_slack(result_images, result_caption, 'result')
    else:
        print("  → 오늘 경기 없음")
    
    # --- 내일 경기 처리 (Preview) ---
    tomorrows_matches = get_tomorrows_matches()
    print(f"\n📅 내일 경기: {len(tomorrows_matches)}개")
    
    if tomorrows_matches:
        # 캡처
        preview_images = []
        for match in tomorrows_matches:
            game_no = match['game_no']
            try:
                image_path = capture_match_preview(game_no)
                preview_images.append(image_path)
            except Exception as e:
                print(f"❌ Preview 캡처 실패 (game_no={game_no}): {e}")
        
        # AI 멘트 생성
        if preview_images:
            preview_caption = generate_caption(tomorrows_matches, team_info, standings, 'preview')
            print(f"\n📝 Preview 멘트:\n{preview_caption[:200]}...")
            
            # Slack 전송
            send_to_slack(preview_images, preview_caption, 'preview')
    else:
        print("  → 내일 경기 없음")
    
    print(f"\n[{datetime.now().isoformat()}] ✅ 완료")


if __name__ == "__main__":
    main()