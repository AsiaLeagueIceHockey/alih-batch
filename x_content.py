"""
X(Twitter) 일본어 컨텐츠 생성 스크립트 - 스레드 형식

GitHub Actions에서 실행되어:
1. Series Review (일요일): 지난 주 경기 결과 요약
2. Series Preview (목요일): 다음 주 경기 예고
3. Slack으로 스레드 형식 텍스트 전송 (복사하여 X에 게시)

X 글자수 제한(280자) 대응:
- 첫 트윗: 요약 + 해시태그
- 후속 트윗: 개별 경기 정보 (리플라이)
"""

import os
import sys
import re
from datetime import datetime, timedelta
from supabase import create_client, Client
from groq import Groq
import requests
from season_config import require_target_season

# --- 환경변수 ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
TARGET_SEASON = require_target_season()

# X 글자수 제한
X_CHAR_LIMIT = 280

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
    """alih_teams에서 팀 정보 조회 (일본어 이름 포함)"""
    response = supabase.table('alih_teams') \
        .select('id, name, english_name, japanese_name') \
        .execute()
    return {team['id']: team for team in response.data}


def get_standings_info() -> dict:
    """alih_standings에서 순위 정보 조회"""
    response = supabase.table('alih_standings') \
        .select('team_id, rank, points, games_played') \
        .eq('season', TARGET_SEASON) \
        .order('rank') \
        .execute()
    return {s['team_id']: s for s in response.data}


def get_weekly_results() -> list:
    """지난 7일간 완료된 경기 조회 (Review용)"""
    now_kst = datetime.utcnow() + timedelta(hours=9)
    today_end = now_kst.replace(hour=23, minute=59, second=59, microsecond=999999)
    week_start = (now_kst - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    response = supabase.table('alih_schedule') \
        .select('id, game_no, match_at, home_alih_team_id, away_alih_team_id, home_alih_team_score, away_alih_team_score') \
        .eq('season', TARGET_SEASON) \
        .gte('match_at', week_start.isoformat()) \
        .lte('match_at', today_end.isoformat()) \
        .order('match_at') \
        .execute()
    
    return [m for m in response.data if m.get('home_alih_team_score') is not None]


def get_upcoming_series() -> list:
    """다음 주 예정된 경기 조회 (Preview용)"""
    now_kst = datetime.utcnow() + timedelta(hours=9)
    
    days_until_friday = (4 - now_kst.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 1
    
    next_friday = now_kst + timedelta(days=days_until_friday)
    series_start = next_friday.replace(hour=0, minute=0, second=0, microsecond=0)
    series_end = (series_start + timedelta(days=9)).replace(hour=23, minute=59, second=59, microsecond=999999)
    
    response = supabase.table('alih_schedule') \
        .select('id, game_no, match_at, home_alih_team_id, away_alih_team_id') \
        .eq('season', TARGET_SEASON) \
        .gte('match_at', series_start.isoformat()) \
        .lte('match_at', series_end.isoformat()) \
        .order('match_at') \
        .execute()
    
    return response.data


# =============================================================================
# 2. 헬퍼 함수
# =============================================================================

def get_jp_team_name(team_info: dict, team_id: int) -> str:
    """팀 일본어 이름 반환"""
    team = team_info.get(team_id, {})
    return team.get('japanese_name') or team.get('english_name', 'Unknown')


def format_standings_jp(team_info: dict, standings: dict) -> str:
    """순위표 포맷"""
    sorted_standings = sorted(standings.values(), key=lambda x: x.get('rank', 99))
    lines = []
    for s in sorted_standings:
        team_id = s['team_id']
        name = get_jp_team_name(team_info, team_id)
        rank = s.get('rank', '?')
        points = s.get('points', 0)
        lines.append(f"{rank}位 {name} ({points}pts)")
    return "\n".join(lines)


def generate_base_hashtags() -> str:
    """기본 해시태그"""
    return "#アジアリーグ #ALIH #アイスホッケー"


# =============================================================================
# 3. 스레드 컨텐츠 생성 (Groq AI)
# =============================================================================

def generate_review_thread(matches: list, team_info: dict, standings: dict) -> list[str]:
    """
    Series Review 스레드 생성
    Returns: [첫 트윗, 리플라이1, 리플라이2, ...]
    """
    if not GROQ_API_KEY:
        print("⚠️ GROQ_API_KEY가 설정되지 않음.")
        return []
    
    client = Groq(api_key=GROQ_API_KEY)
    
    now_kst = datetime.utcnow() + timedelta(hours=9)
    week_start = now_kst - timedelta(days=6)
    date_range = f"{week_start.strftime('%m/%d')}〜{now_kst.strftime('%m/%d')}"
    
    # 경기 정보 준비
    match_details = []
    for match in matches:
        home_name = get_jp_team_name(team_info, match['home_alih_team_id'])
        away_name = get_jp_team_name(team_info, match['away_alih_team_id'])
        home_score = match.get('home_alih_team_score', 0)
        away_score = match.get('away_alih_team_score', 0)
        game_no = match['game_no']
        match_dt = datetime.fromisoformat(match['match_at'].replace('Z', '+00:00')) + timedelta(hours=9)
        date_str = match_dt.strftime('%m/%d')
        
        match_details.append({
            'date': date_str,
            'home': home_name,
            'away': away_name,
            'home_score': home_score,
            'away_score': away_score,
            'game_no': game_no,
            'link': f"https://alhockey.fans/schedule/{game_no}?lang=jp&season={TARGET_SEASON}"
        })
    
    standings_text = format_standings_jp(team_info, standings)
    
    # 팀 정보 컨텍스트
    team_context = "\n".join([
        f"- {t.get('japanese_name', t.get('english_name'))}"
        for t in team_info.values() if t.get('japanese_name') or t.get('english_name')
    ])
    
    prompt = f"""あなたはアジアリーグアイスホッケーのX(@alhockey_fans)運営者です。
今週の試合結果をX(Twitter)のスレッド形式で投稿します。

【重要】各ツイートは必ず280文字以内にしてください。

## スレッド構成
1. **メインツイート（1つ目）**: 今週の総括要約 + ハッシュタグ
2. **リプライツイート（2つ目以降）**: 各試合ごとに1ツイート

## チーム情報
{team_context}

## 今週の試合結果 ({date_range})
"""
    
    # 각 경기별 상세 정보 (링크 포함)
    for i, m in enumerate(match_details, 1):
        prompt += f"\n{i}. {m['date']} {m['home']} {m['home_score']}-{m['away_score']} {m['away']}"
        prompt += f"\n   링크: {m['link']}"
    
    prompt += f"""

## 現在の順位
{standings_text}

## 出力形式（JSONで出力）
以下の形式で出力してください：
{{
  "main_tweet": "メインツイートの内容（280文字以内、ハッシュタグ含む）",
  "reply_tweets": [
    "1試合目のツイート（280文字以内）",
    "2試合目のツイート（280文字以内）",
    ...
  ]
}}

## メインツイートの要件
- 今週の結果の簡潔な総括（例：「激戦の1週間！首位レッドイーグルスが2連勝🔥」）
- 絵文字使用（🏒❄️🔥など）
- 最後に #アジアリーグ #ALIH #アイスホッケー
- 280文字以内

## リプライツイートの要件（各試合ごと）
- 試合日時と対戦カード
- スコアと簡単な一言コメント
- 【重要】各試合のリンクは上記の「リンク」をそのまま使用してください。絶対に変更しないでください。
- 280文字以内
- 絵文字使用

必ずJSON形式で出力してください。"""

    print(f"\n{'='*60}")
    print(f"📤 [Groq API] Series Review スレッド生成")
    print(f"{'='*60}")
    
    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = completion.choices[0].message.content
        
        # JSON 파싱 시도
        import json
        # JSON 블록 추출
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            data = json.loads(json_match.group())
            tweets = [data.get('main_tweet', '')]
            tweets.extend(data.get('reply_tweets', []))
            return tweets
        else:
            print("⚠️ JSON 파싱 실패, 원본 반환")
            return [response_text]
            
    except Exception as e:
        print(f"❌ Groq API エラー: {e}")
        return []


def generate_preview_thread(matches: list, team_info: dict, standings: dict) -> list[str]:
    """
    Series Preview 스레드 생성
    Returns: [첫 트윗, 리플라이1, 리플라이2, ...]
    """
    if not GROQ_API_KEY:
        print("⚠️ GROQ_API_KEY가 설정되지 않음.")
        return []
    
    client = Groq(api_key=GROQ_API_KEY)
    
    # 날짜 범위
    if matches:
        first_match = datetime.fromisoformat(matches[0]['match_at'].replace('Z', '+00:00')) + timedelta(hours=9)
        last_match = datetime.fromisoformat(matches[-1]['match_at'].replace('Z', '+00:00')) + timedelta(hours=9)
        date_range = f"{first_match.strftime('%m/%d')}〜{last_match.strftime('%m/%d')}"
    else:
        now_kst = datetime.utcnow() + timedelta(hours=9)
        date_range = f"{(now_kst + timedelta(days=1)).strftime('%m/%d')}〜"
    
    # 경기 정보 준비
    match_details = []
    for match in matches:
        home_name = get_jp_team_name(team_info, match['home_alih_team_id'])
        away_name = get_jp_team_name(team_info, match['away_alih_team_id'])
        game_no = match['game_no']
        match_dt = datetime.fromisoformat(match['match_at'].replace('Z', '+00:00')) + timedelta(hours=9)
        datetime_str = match_dt.strftime('%m/%d %H:%M')
        
        # 순위 정보
        home_rank = standings.get(match['home_alih_team_id'], {}).get('rank', '?')
        away_rank = standings.get(match['away_alih_team_id'], {}).get('rank', '?')
        
        match_details.append({
            'datetime': datetime_str,
            'home': home_name,
            'away': away_name,
            'home_rank': home_rank,
            'away_rank': away_rank,
            'game_no': game_no,
            'link': f"https://alhockey.fans/schedule/{game_no}?lang=jp&season={TARGET_SEASON}"
        })
    
    standings_text = format_standings_jp(team_info, standings)
    
    # 팀 정보 컨텍스트
    team_context = "\n".join([
        f"- {t.get('japanese_name', t.get('english_name'))}"
        for t in team_info.values() if t.get('japanese_name') or t.get('english_name')
    ])
    
    prompt = f"""あなたはアジアリーグアイスホッケーのX(@alhockey_fans)運営者です。
来週の試合予定をX(Twitter)のスレッド形式で投稿します。

【重要】各ツイートは必ず280文字以内にしてください。

## スレッド構成
1. **メインツイート（1つ目）**: 来週の見どころ総括 + ハッシュタグ
2. **リプライツイート（2つ目以降）**: 各試合ごとに1ツイート

## チーム情報
{team_context}

## 来週の試合予定 ({date_range})
"""
    
    # 각 경기별 상세 정보 (링크 포함)
    for i, m in enumerate(match_details, 1):
        prompt += f"\n{i}. {m['datetime']} {m['home']}({m['home_rank']}位) vs {m['away']}({m['away_rank']}位)"
        prompt += f"\n   링크: {m['link']}"
    
    prompt += f"""

## 現在の順位
{standings_text}

## 出力形式（JSONで出力）
以下の形式で出力してください：
{{
  "main_tweet": "メインツイートの内容（280文字以内、ハッシュタグ含む）",
  "reply_tweets": [
    "1試合目のツイート（280文字以内）",
    "2試合目のツイート（280文字以内）",
    ...
  ]
}}

## メインツイートの要件
- 来週の見どころの簡潔な総括（例：「来週は首位決戦！見逃せない熱い1週間🔥」）
- 絵文字使用（🏒⚔️🔥📅など）
- 最後に #アジアリーグ #ALIH #アイスホッケー
- 280文字以内

## リプライツイートの要件（各試合ごと）
- 試合日時と対戦カード（順位含む）
- 見どころや注目ポイントを一言で
- 【重要】各試合のリンクは上記の「リンク」をそのまま使用してください。絶対に変更しないでください。
- 280文字以内
- 絵文字使用
- 選手名は使用しない（データがないため）

必ずJSON形式で出力してください。"""

    print(f"\n{'='*60}")
    print(f"📤 [Groq API] Series Preview スレッド生成")
    print(f"{'='*60}")
    
    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = completion.choices[0].message.content
        
        # JSON 파싱 시도
        import json
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            data = json.loads(json_match.group())
            tweets = [data.get('main_tweet', '')]
            tweets.extend(data.get('reply_tweets', []))
            return tweets
        else:
            print("⚠️ JSON 파싱 실패, 원본 반환")
            return [response_text]
            
    except Exception as e:
        print(f"❌ Groq API エラー: {e}")
        return []


# =============================================================================
# 4. Slack 전송
# =============================================================================

def clean_markdown(text: str) -> str:
    """마크다운 문법 제거"""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    return text


def send_thread_to_slack(tweets: list[str], content_type: str):
    """Slack Webhook으로 스레드 형식 컨텐츠 전송"""
    if not tweets:
        print("⚠️ 전송할 트윗이 없습니다.")
        return
    
    emoji = "📊" if content_type == "review" else "🔮"
    title = "Series Review" if content_type == "review" else "Series Preview"
    
    # 각 트윗 글자수 체크
    for i, tweet in enumerate(tweets):
        char_count = len(tweet)
        status = "✅" if char_count <= X_CHAR_LIMIT else "⚠️ 초과!"
        print(f"  Tweet {i+1}: {char_count}자 {status}")
    
    if not SLACK_WEBHOOK_URL:
        print("⚠️ SLACK_WEBHOOK_URL 미설정. Slack 전송 생략.")
        print("\n" + "="*60)
        print("📝 생성된 스레드:")
        print("="*60)
        for i, tweet in enumerate(tweets):
            label = "🧵 메인" if i == 0 else f"↪️ 리플라이 {i}"
            print(f"\n{label} ({len(tweet)}자):")
            print(tweet)
        return
    
    # Slack 블록 구성
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} X Thread: {title}", "emoji": True}
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"🧵 스레드 형식: 메인 1개 + 리플라이 {len(tweets)-1}개"}
            ]
        },
        {"type": "divider"}
    ]
    
    # 각 트윗 추가
    for i, tweet in enumerate(tweets):
        clean_tweet = clean_markdown(tweet)
        char_count = len(clean_tweet)
        char_status = "✅" if char_count <= X_CHAR_LIMIT else "⚠️초과"
        
        label = "🧵 **메인 트윗**" if i == 0 else f"↪️ **리플라이 {i}**"
        
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{label} ({char_count}자 {char_status})\n```{clean_tweet}```"}
        })
    
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": "📋 위 순서대로 @alhockey_fans 에서 스레드로 게시하세요"}
        ]
    })
    
    payload = {"blocks": blocks}
    
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload)
        if response.status_code == 200:
            print(f"✅ Slack 스레드 전송 완료 ({content_type})")
        else:
            print(f"❌ Slack 전송 실패: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Slack 전송 에러: {e}")


# =============================================================================
# 5. 메인 함수
# =============================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: python x_content.py <review|preview>")
        print("  review  - 지난 주 경기 결과 요약 (일요일 발행)")
        print("  preview - 다음 주 경기 예고 (목요일 발행)")
        sys.exit(1)
    
    content_type = sys.argv[1].lower()
    if content_type not in ['review', 'preview']:
        print(f"❌ 잘못된 content_type: {content_type}")
        sys.exit(1)
    
    print(f"[{datetime.now().isoformat()}] 🚀 X Thread Generator 시작 ({content_type})")
    print(f"📏 X 글자수 제한: {X_CHAR_LIMIT}자")
    
    # Supabase 초기화
    init_supabase()
    
    # 팀 정보 & 순위 정보 로드
    team_info = get_team_info()
    standings = get_standings_info()
    print(f"📊 팀 정보 로드: {len(team_info)}개 팀")
    
    # 스레드 생성
    if content_type == 'review':
        matches = get_weekly_results()
        print(f"📅 지난 주 경기: {len(matches)}개")
        
        if not matches:
            print("⚠️ 지난 주 경기 없음. 종료.")
            return
        
        tweets = generate_review_thread(matches, team_info, standings)
        
    else:  # preview
        matches = get_upcoming_series()
        print(f"📅 다음 주 경기: {len(matches)}개")
        
        if not matches:
            print("⚠️ 다음 주 경기 없음. 종료.")
            return
        
        tweets = generate_preview_thread(matches, team_info, standings)
    
    if tweets:
        print(f"\n🧵 생성된 스레드: {len(tweets)}개 트윗")
        send_thread_to_slack(tweets, content_type)
    else:
        print("❌ 스레드 생성 실패")
    
    print(f"\n[{datetime.now().isoformat()}] ✅ 완료")


if __name__ == "__main__":
    main()
