"""
X(Twitter) 일본어 컨텐츠 생성 스크립트

GitHub Actions에서 실행되어:
1. Series Review (일요일): 지난 주 경기 결과 요약
2. Series Preview (목요일): 다음 주 경기 예고
3. Slack으로 텍스트 전송 (복사하여 X에 게시)
"""

import os
import sys
import re
from datetime import datetime, timedelta
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
    alih_teams에서 팀 정보 조회 (일본어 이름 포함)
    Returns: {team_id: {'name': 한국어명, 'english_name': 영어명, 'japanese_name': 일본어명}}
    """
    response = supabase.table('alih_teams') \
        .select('id, name, english_name, japanese_name') \
        .execute()
    
    return {team['id']: team for team in response.data}


def get_standings_info() -> dict:
    """
    alih_standings에서 순위 정보 조회
    """
    response = supabase.table('alih_standings') \
        .select('team_id, rank, points, games_played') \
        .order('rank') \
        .execute()
    
    return {s['team_id']: s for s in response.data}


def get_weekly_results() -> list:
    """
    지난 7일간(오늘 포함) 완료된 경기 조회 (Review용)
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
    return [m for m in response.data if m.get('home_alih_team_score') is not None]


def get_upcoming_series() -> list:
    """
    다음 주 예정된 경기 조회 (Preview용)
    - 다음 금요일부터 그 다음주 일요일까지
    KST 기준
    """
    now_kst = datetime.utcnow() + timedelta(hours=9)
    
    # 다음 금요일 찾기 (오늘이 목요일이라면 내일)
    days_until_friday = (4 - now_kst.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 1  # 목요일에 실행, 내일이 금요일
    
    next_friday = now_kst + timedelta(days=days_until_friday)
    series_start = next_friday.replace(hour=0, minute=0, second=0, microsecond=0)
    series_end = (series_start + timedelta(days=9)).replace(hour=23, minute=59, second=59, microsecond=999999)
    
    response = supabase.table('alih_schedule') \
        .select('id, game_no, match_at, home_alih_team_id, away_alih_team_id') \
        .gte('match_at', series_start.isoformat()) \
        .lte('match_at', series_end.isoformat()) \
        .order('match_at') \
        .execute()
    
    return response.data


# =============================================================================
# 2. AI 컨텐츠 생성 (Groq) - 일본어
# =============================================================================

def get_jp_team_name(team_info: dict, team_id: int) -> str:
    """팀 일본어 이름 반환 (없으면 영어 이름)"""
    team = team_info.get(team_id, {})
    return team.get('japanese_name') or team.get('english_name', 'Unknown')


def format_results_for_review(matches: list, team_info: dict) -> str:
    """Review용 경기 결과 포맷"""
    lines = []
    for match in matches:
        home_id = match['home_alih_team_id']
        away_id = match['away_alih_team_id']
        home_name = get_jp_team_name(team_info, home_id)
        away_name = get_jp_team_name(team_info, away_id)
        home_score = match.get('home_alih_team_score', 0)
        away_score = match.get('away_alih_team_score', 0)
        game_no = match['game_no']
        
        # 날짜
        match_dt = datetime.fromisoformat(match['match_at'].replace('Z', '+00:00')) + timedelta(hours=9)
        date_str = match_dt.strftime('%m/%d')
        
        lines.append(f"• {date_str} {home_name} {home_score}-{away_score} {away_name}")
        lines.append(f"  👉 https://alhockey.fans/schedule/{game_no}?lang=jp")
    
    return "\n".join(lines) if lines else "今週の試合はありませんでした。"


def format_matches_for_preview(matches: list, team_info: dict) -> str:
    """Preview용 경기 일정 포맷"""
    lines = []
    for i, match in enumerate(matches, 1):
        home_id = match['home_alih_team_id']
        away_id = match['away_alih_team_id']
        home_name = get_jp_team_name(team_info, home_id)
        away_name = get_jp_team_name(team_info, away_id)
        game_no = match['game_no']
        
        # 날짜/시간
        match_dt = datetime.fromisoformat(match['match_at'].replace('Z', '+00:00')) + timedelta(hours=9)
        datetime_str = match_dt.strftime('%m/%d %H:%M')
        
        lines.append(f"{i}️⃣ {home_name} vs {away_name}")
        lines.append(f"   📅 {datetime_str}")
        lines.append(f"   👉 https://alhockey.fans/schedule/{game_no}?lang=jp")
    
    return "\n".join(lines) if lines else "来週の試合はありません。"


def format_standings_jp(team_info: dict, standings: dict) -> str:
    """현재 순위표를 일본어로 포맷"""
    sorted_standings = sorted(standings.values(), key=lambda x: x.get('rank', 99))
    
    lines = []
    for s in sorted_standings:
        team_id = s['team_id']
        name = get_jp_team_name(team_info, team_id)
        rank = s.get('rank', '?')
        points = s.get('points', 0)
        lines.append(f"{rank}位 {name} ({points}pts)")
    
    return "\n".join(lines)


def generate_hashtags(matches: list, team_info: dict) -> str:
    """경기에 등장한 팀 기반 해시태그 생성"""
    team_ids = set()
    for match in matches:
        team_ids.add(match['home_alih_team_id'])
        team_ids.add(match['away_alih_team_id'])
    
    # 기본 해시태그
    tags = ["#アジアリーグアイスホッケー", "#ALIH", "#アイスホッケー"]
    
    # 팀별 해시태그 (일본어 이름 기반, 공백 제거)
    for team_id in team_ids:
        jp_name = get_jp_team_name(team_info, team_id)
        if jp_name and jp_name != 'Unknown':
            clean_name = jp_name.replace(" ", "").replace("　", "")
            tags.append(f"#{clean_name}")
    
    return " ".join(tags)


def generate_review_content(matches: list, team_info: dict, standings: dict) -> str:
    """Series Review 컨텐츠 생성 (Groq AI)"""
    if not GROQ_API_KEY:
        print("⚠️ GROQ_API_KEY가 설정되지 않음.")
        return None
    
    client = Groq(api_key=GROQ_API_KEY)
    
    # 날짜 범위
    now_kst = datetime.utcnow() + timedelta(hours=9)
    week_start = now_kst - timedelta(days=6)
    date_range = f"{week_start.strftime('%m/%d')}〜{now_kst.strftime('%m/%d')}"
    
    results_text = format_results_for_review(matches, team_info)
    standings_text = format_standings_jp(team_info, standings)
    hashtags = generate_hashtags(matches, team_info)
    
    # 팀 정보 컨텍스트
    team_context = "\n".join([
        f"- {t.get('japanese_name', t.get('english_name'))} (英語: {t['english_name']})"
        for t in team_info.values() if t.get('japanese_name') or t.get('english_name')
    ])
    
    example = """📊 今週のアジアリーグ結果 (1/6〜1/12) 🏒

🔥 試合結果
• 1/6 HLアンヤン 4-2 日光アイスバックス
  👉 https://alhockey.fans/schedule/123?lang=jp
• 1/7 レッドイーグルス北海道 3-1 横浜グリッツ
  👉 https://alhockey.fans/schedule/124?lang=jp
• 1/8 東北フリーブレイズ 2-3 スターズ神戸 (OT)
  👉 https://alhockey.fans/schedule/125?lang=jp

📈 現在の順位
1位 レッドイーグルス北海道 (32pts)
2位 HLアンヤン (28pts)
3位 日光アイスバックス (25pts)
...

激戦が続くアジアリーグ！来週も注目試合が盛りだくさん！🔥

詳しい情報は👉 @alhockey_fans をフォロー！
🔗 https://alhockey.fans

#アジアリーグアイスホッケー #ALIH #アイスホッケー #HLアンヤン"""
    
    prompt = f"""あなたはアジアリーグアイスホッケーのXアカウント運営者です。
今週の試合結果をまとめた「シリーズレビュー」投稿を日本語で作成してください。

[チーム情報 - 必ずこの日本語名を使用してください]
{team_context}

[今週の試合結果 - {date_range}]
{results_text}

[現在の順位表]
{standings_text}

[作成例]
{example}

[要件]
1. 各試合結果を簡潔に記載し、各試合ごとにリンクを含める
2. 現在の順位状況を記載
3. 絵文字を効果的に使用（🏒❄️🔥🎯など）
4. 最後に @alhockey_fans と https://alhockey.fans を含める
5. ハッシュタグ: {hashtags}
6. X(Twitter)の280文字制限は気にせず、必要な情報を全て含めてください
7. 日本のアイスホッケーファンに親しみやすい文体で

投稿文を作成してください。"""

    print(f"\n{'='*60}")
    print(f"📤 [Groq API] Series Review プロンプト送信")
    print(f"{'='*60}")
    
    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq API エラー: {e}")
        return None


def generate_preview_content(matches: list, team_info: dict, standings: dict) -> str:
    """Series Preview 컨텐츠 생성 (Groq AI)"""
    if not GROQ_API_KEY:
        print("⚠️ GROQ_API_KEY가 설정되지 않음.")
        return None
    
    client = Groq(api_key=GROQ_API_KEY)
    
    # 날짜 범위 계산
    if matches:
        first_match = datetime.fromisoformat(matches[0]['match_at'].replace('Z', '+00:00')) + timedelta(hours=9)
        last_match = datetime.fromisoformat(matches[-1]['match_at'].replace('Z', '+00:00')) + timedelta(hours=9)
        date_range = f"{first_match.strftime('%m/%d')}〜{last_match.strftime('%m/%d')}"
    else:
        now_kst = datetime.utcnow() + timedelta(hours=9)
        date_range = f"{(now_kst + timedelta(days=1)).strftime('%m/%d')}〜"
    
    matches_text = format_matches_for_preview(matches, team_info)
    standings_text = format_standings_jp(team_info, standings)
    hashtags = generate_hashtags(matches, team_info)
    
    # 팀 정보 컨텍스트
    team_context = "\n".join([
        f"- {t.get('japanese_name', t.get('english_name'))} (英語: {t['english_name']})"
        for t in team_info.values() if t.get('japanese_name') or t.get('english_name')
    ])
    
    example = """🔮 来週のアジアリーグプレビュー (1/13〜1/19) 🏒

⚔️ 注目の対戦

1️⃣ HLアンヤン vs レッドイーグルス北海道
   首位攻防戦！🔥
   📅 1/13 19:00
   👉 https://alhockey.fans/schedule/130?lang=jp

2️⃣ 東北フリーブレイズ vs 日光アイスバックス  
   中位争いの直接対決！
   📅 1/14 18:00
   👉 https://alhockey.fans/schedule/131?lang=jp

📈 現在の順位
1位 レッドイーグルス北海道 (32pts)
2位 HLアンヤン (28pts)
...

今シーズンも終盤戦！熱い戦いをお見逃しなく！🔥

試合情報は👉 @alhockey_fans
🔗 https://alhockey.fans

#アジアリーグアイスホッケー #ALIH #レッドイーグルス"""
    
    prompt = f"""あなたはアジアリーグアイスホッケーのXアカウント運営者です。
来週の試合予定をまとめた「シリーズプレビュー」投稿を日本語で作成してください。

[チーム情報 - 必ずこの日本語名を使用してください]
{team_context}

[来週の試合予定 - {date_range}]
{matches_text}

[現在の順位表 - 対戦の重要度を判断するのに参考にしてください]
{standings_text}

[作成例]
{example}

[要件]
1. 各試合の見どころ・注目ポイントを簡潔に記載
2. 順位争いや対戦カードの重要性を言及
3. 各試合ごとにリンクを含める
4. 絵文字を効果的に使用（🏒⚔️🔥📅など）
5. 最後に @alhockey_fans と https://alhockey.fans を含める
6. ハッシュタグ: {hashtags}
7. 日本のアイスホッケーファンにワクワク感を与える文体で
8. 注意: 選手名や個人記録など、提供されていない情報は絶対に言及しないでください

投稿文を作成してください。"""

    print(f"\n{'='*60}")
    print(f"📤 [Groq API] Series Preview プロンプト送信")
    print(f"{'='*60}")
    
    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq API エラー: {e}")
        return None


# =============================================================================
# 3. Slack 전송
# =============================================================================

def clean_markdown(text: str) -> str:
    """마크다운 문법 제거"""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    return text


def send_to_slack(content: str, content_type: str):
    """Slack Webhook으로 컨텐츠 전송"""
    if not SLACK_WEBHOOK_URL:
        print("⚠️ SLACK_WEBHOOK_URL 미설정. Slack 전송 생략.")
        print("\n" + "="*60)
        print("📝 생성된 컨텐츠:")
        print("="*60)
        print(content)
        return
    
    emoji = "📊" if content_type == "review" else "🔮"
    title = "Series Review" if content_type == "review" else "Series Preview"
    
    clean_content = clean_markdown(content)
    
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} X Content: {title}", "emoji": True}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"以下の内容をXに投稿してください:\n\n```{clean_content}```"}
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "📋 上のテキストをコピーして @alhockey_fans で投稿してください"}
            ]
        }
    ]
    
    payload = {"blocks": blocks}
    
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload)
        if response.status_code == 200:
            print(f"✅ Slack 전송 완료 ({content_type})")
        else:
            print(f"❌ Slack 전송 실패: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Slack 전송 에러: {e}")


# =============================================================================
# 4. 메인 함수
# =============================================================================

def main():
    # 인자로 content_type 받기 (review/preview)
    if len(sys.argv) < 2:
        print("Usage: python x_content.py <review|preview>")
        print("  review  - 지난 주 경기 결과 요약 (일요일 발행)")
        print("  preview - 다음 주 경기 예고 (목요일 발행)")
        sys.exit(1)
    
    content_type = sys.argv[1].lower()
    if content_type not in ['review', 'preview']:
        print(f"❌ 잘못된 content_type: {content_type}")
        print("  'review' 또는 'preview'를 사용하세요.")
        sys.exit(1)
    
    print(f"[{datetime.now().isoformat()}] 🚀 X Content Generator 시작 ({content_type})")
    
    # Supabase 초기화
    init_supabase()
    
    # 팀 정보 & 순위 정보 로드
    team_info = get_team_info()
    standings = get_standings_info()
    print(f"📊 팀 정보 로드: {len(team_info)}개 팀")
    
    # 컨텐츠 생성
    if content_type == 'review':
        matches = get_weekly_results()
        print(f"📅 지난 주 경기: {len(matches)}개")
        
        if not matches:
            print("⚠️ 지난 주 경기 없음. 종료.")
            return
        
        content = generate_review_content(matches, team_info, standings)
        
    else:  # preview
        matches = get_upcoming_series()
        print(f"📅 다음 주 경기: {len(matches)}개")
        
        if not matches:
            print("⚠️ 다음 주 경기 없음. 종료.")
            return
        
        content = generate_preview_content(matches, team_info, standings)
    
    if content:
        print(f"\n📝 생성된 컨텐츠 (미리보기):\n{content[:300]}...")
        send_to_slack(content, content_type)
    else:
        print("❌ 컨텐츠 생성 실패")
    
    print(f"\n[{datetime.now().isoformat()}] ✅ 완료")


if __name__ == "__main__":
    main()
