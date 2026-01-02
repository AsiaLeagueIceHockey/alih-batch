"""
Live URL 자동 갱신 스크립트

경기 시작 전 홈팀 유튜브 채널에서 라이브 스트림을 검색하여
alih_schedule 테이블의 live_url을 자동으로 채웁니다.

실행 주기: 15분 간격 (GitHub Actions)

지원하는 팀 (4팀):
- HL Anyang (한국어 중계)
- RED EAGLES HOKKAIDO (일본어 중계)
- TOHOKU FREE BLADES (일본어 중계)
- YOKOHAMA GRITS (일본어 중계)
"""

import os
import subprocess
import json
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from dateutil import parser as date_parser  # 날짜 파싱용

# --- 1. Supabase 클라이언트 초기화 ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise EnvironmentError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 2. 팀별 유튜브 채널 매핑 (4팀만) ---
# english_name 기반으로 매핑 (DB에서 team_id를 동적으로 가져옴)
TEAM_YOUTUBE_CHANNELS = {
    "HL Anyang": {
        "channel_url": "https://www.youtube.com/@hlanyang",
        "language": "ko",
    },
    "RED EAGLES HOKKAIDO": {
        "channel_url": "https://www.youtube.com/@OjiEaglesFan",
        "language": "ja",
    },
    "TOHOKU FREE BLADES": {
        "channel_url": "https://www.youtube.com/@freeblades2009",
        "language": "ja",
    },
    "YOKOHAMA GRITS": {
        "channel_url": "https://www.youtube.com/@grits5937",
        "language": "ja",
    },
}

# --- 3. 팀명 매칭용 키워드 (한글, 영문, 일본어) ---
# 라이브 스트림 제목에서 상대팀을 매칭하기 위한 키워드
# english_name 기반으로 매핑
TEAM_KEYWORDS = {
    "HL Anyang": ["안양", "anyang", "hla", "アニャン", "ハラ", "hl안양"],
    "RED EAGLES HOKKAIDO": ["레드이글스", "red eagles", "hokkaido", "reh", "レッドイーグルス", "北海道", "王子"],
    "TOHOKU FREE BLADES": ["프리블레이즈", "freeblades", "tohoku", "tfb", "フリーブレイズ", "東北"],
    "NIKKO ICEBUCKS": ["아이스벅스", "icebucks", "nikko", "nib", "アイスバックス", "日光"],
    "YOKOHAMA GRITS": ["그리츠", "grits", "yokohama", "yok", "グリッツ", "横浜"],
    "STARS KOBE": ["고베", "kobe", "stars", "stk", "スターズ", "神戸"],
}

# 라이브 스트림 제목에서 사용될 수 있는 키워드 (경기 중계임을 나타내는)
LIVE_KEYWORDS = [
    "live", "라이브", "생중계", "중계", "ライブ", "生放送", "生配信",
    "vs", "対", "戦", "경기", "試合", "game", "match",
    "asia league", "아시아리그", "アジアリーグ"
]


# --- 4. 팀 정보 가져오기 ---
def get_team_info() -> tuple[dict, dict]:
    """
    alih_teams 테이블에서 팀 정보를 가져옵니다.
    
    반환:
    - team_by_id: {team_id: {"english_name": str, "name": str (한글)}}
    - team_id_by_name: {english_name: team_id}
    """
    try:
        response = supabase.table('alih_teams').select('id, english_name, name').execute()
        if response.data:
            team_by_id = {team['id']: {"english_name": team['english_name'], "name": team['name']} for team in response.data}
            team_id_by_name = {team['english_name']: team['id'] for team in response.data}
            return team_by_id, team_id_by_name
        return {}, {}
    except Exception as e:
        print(f"[ERROR] Failed to fetch team info: {e}")
        return {}, {}


# --- 5. 곧 시작할 경기 조회 ---
def get_upcoming_games(supported_team_ids: list) -> list:
    """
    향후 6시간 이내에 시작하고 live_url이 없는 경기를 조회합니다.
    홈팀이 라이브 중계 채널을 가진 팀인 경우만 대상으로 합니다.
    """
    now = datetime.now(timezone.utc)
    six_hours_later = now + timedelta(hours=6)
    
    try:
        response = supabase.table('alih_schedule') \
            .select('id, game_no, match_at, home_alih_team_id, away_alih_team_id, live_url') \
            .gte('match_at', now.isoformat()) \
            .lte('match_at', six_hours_later.isoformat()) \
            .in_('home_alih_team_id', supported_team_ids) \
            .execute()
        
        if not response.data:
            return []
        
        # live_url이 없거나 비어있는 경기만 필터링
        return [game for game in response.data if not game.get('live_url')]
    
    except Exception as e:
        print(f"[ERROR] Failed to fetch upcoming games: {e}")
        return []


# --- 6. yt-dlp로 채널의 라이브/예정 스트림 검색 ---
def find_live_streams(channel_url: str) -> list:
    """
    yt-dlp를 사용하여 채널의 라이브 또는 예정된 스트림을 검색합니다.
    스트림의 예정 시작 시간(release_timestamp)도 함께 가져옵니다.
    """
    # 라이브 탭 URL 생성
    live_url = f"{channel_url}/streams"
    
    cmd = [
        'yt-dlp',
        '--flat-playlist',
        '--dump-json',
        '--playlist-end', '10',  # 최근 10개만
        '--no-warnings',
        live_url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            print(f"  [WARN] yt-dlp returned non-zero: {result.stderr[:200] if result.stderr else 'no error message'}")
            return []
        
        streams = []
        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    video_data = json.loads(line)
                    # 예정 시작 시간 가져오기 (Unix timestamp)
                    release_timestamp = video_data.get('release_timestamp')
                    timestamp = video_data.get('timestamp')
                    
                    # release_timestamp가 없으면 timestamp 사용
                    scheduled_time = None
                    if release_timestamp:
                        scheduled_time = datetime.fromtimestamp(release_timestamp, tz=timezone.utc)
                    elif timestamp:
                        scheduled_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                    
                    streams.append({
                        'id': video_data.get('id'),
                        'title': video_data.get('title', ''),
                        'url': f"https://www.youtube.com/watch?v={video_data.get('id')}",
                        'is_live': video_data.get('is_live', False),
                        'live_status': video_data.get('live_status'),  # is_upcoming, is_live, was_live
                        'scheduled_time': scheduled_time,  # 예정 시작 시간
                    })
                except json.JSONDecodeError:
                    continue
        
        return streams
    
    except subprocess.TimeoutExpired:
        print(f"  [WARN] yt-dlp timed out for {channel_url}")
        return []
    except Exception as e:
        print(f"  [ERROR] yt-dlp failed: {e}")
        return []


# --- 7. 스트림과 경기 매칭 ---
def match_stream_to_game(streams: list, game: dict, team_by_id: dict) -> str | None:
    """
    라이브 스트림의 예정 시작 시간과 경기 시간을 비교하여 매칭합니다.
    
    매칭 전략 (우선순위):
    1. 스트림 예정 시작 시간이 경기 시간과 ±2시간 이내 + 팀 키워드 매칭
    2. is_upcoming/is_live 상태 + 팀 키워드 매칭 (시간 정보 없는 경우)
    3. 날짜 + 팀 키워드 매칭 (fallback)
    
    이 방식으로 연속 시리즈 경기(1/2, 1/3, 1/4)를 정확하게 구분합니다.
    """
    away_team_id = game['away_alih_team_id']
    away_team_info = team_by_id.get(away_team_id, {})
    away_english_name = away_team_info.get('english_name', '')
    away_korean_name = away_team_info.get('name', '')
    
    # 상대팀 키워드 가져오기
    away_keywords = list(TEAM_KEYWORDS.get(away_english_name, []))
    
    # 한글명도 키워드에 추가
    if away_korean_name:
        away_keywords.append(away_korean_name.lower())
    
    # 경기 시간 파싱 (ISO 형식)
    game_time = date_parser.parse(game['match_at'])
    
    # 시간 허용 오차 (±2시간)
    time_tolerance = timedelta(hours=2)
    
    # 1차: 예정 시작 시간으로 매칭 (가장 정확함)
    for stream in streams:
        title = stream['title']
        title_lower = title.lower()
        scheduled_time = stream.get('scheduled_time')
        
        if not scheduled_time:
            continue
        
        # 시간 차이 계산
        time_diff = abs(scheduled_time - game_time)
        
        if time_diff <= time_tolerance:
            # 시간이 맞으면 팀 키워드도 확인 (추가 검증)
            for keyword in away_keywords:
                if keyword.lower() in title_lower:
                    print(f"  [MATCH] Time match ({scheduled_time.strftime('%Y-%m-%d %H:%M')}) + Team '{keyword}'")
                    print(f"    Title: {title[:60]}...")
                    return stream['url']
            
            # 팀 키워드 없어도 시간이 정확히 맞으면 매칭 (같은 팀 연속 경기는 시간으로 구분)
            print(f"  [MATCH] Time match ({scheduled_time.strftime('%Y-%m-%d %H:%M')}) - no team keyword but time matched")
            print(f"    Title: {title[:60]}...")
            return stream['url']
    
    # 2차: is_upcoming/is_live 상태 + 팀 키워드 (시간 정보 없는 경우)
    for stream in streams:
        title = stream['title']
        title_lower = title.lower()
        live_status = stream.get('live_status', '')
        is_live_or_upcoming = (
            stream.get('is_live', False) or
            live_status in ['is_upcoming', 'is_live']
        )
        
        if not is_live_or_upcoming:
            continue
        
        # 이미 1차에서 scheduled_time 체크됨, 여기는 scheduled_time 없는 경우만
        if stream.get('scheduled_time'):
            continue
        
        for keyword in away_keywords:
            if keyword.lower() in title_lower:
                print(f"  [MATCH] Live/Upcoming + Team '{keyword}' (no time info)")
                print(f"    Title: {title[:60]}...")
                return stream['url']
    
    # 3차: 날짜 + 팀 키워드 매칭 (fallback - 과거 스트림용)
    match_date = game['match_at'][:10]  # YYYY-MM-DD
    date_patterns = [
        match_date.replace('-', '.'),  # 2026.01.02
        match_date.replace('-', '/'),  # 2026/01/02
        match_date[5:].replace('-', '.'),  # 01.02
        match_date[5:].replace('-', '/'),  # 01/02
        f"{int(match_date[5:7])}月{int(match_date[8:10])}日",  # 1月2日
    ]
    
    for stream in streams:
        title = stream['title']
        title_lower = title.lower()
        
        # 날짜 매칭 확인
        date_matched = False
        matched_date_pattern = None
        for date_pattern in date_patterns:
            if date_pattern in title:
                date_matched = True
                matched_date_pattern = date_pattern
                break
        
        if not date_matched:
            continue
        
        # 날짜 + 팀 키워드 매칭
        for keyword in away_keywords:
            if keyword.lower() in title_lower:
                print(f"  [MATCH] Date '{matched_date_pattern}' + Team '{keyword}'")
                print(f"    Title: {title[:50]}...")
                return stream['url']
    
    return None


# --- 8. live_url 업데이트 ---
def update_live_url(game_id: int, live_url: str) -> bool:
    """
    alih_schedule 테이블의 live_url을 업데이트합니다.
    """
    try:
        supabase.table('alih_schedule') \
            .update({'live_url': live_url}) \
            .eq('id', game_id) \
            .execute()
        return True
    except Exception as e:
        print(f"  [ERROR] Failed to update live_url: {e}")
        return False


# --- 9. 메인 함수 ---
def main():
    print(f"[{datetime.now().isoformat()}] Starting live URL updater...")
    
    # 팀 정보 가져오기
    team_by_id, team_id_by_name = get_team_info()
    if not team_by_id:
        print("[ERROR] Failed to load team info. Exiting.")
        return
    
    print(f"Loaded {len(team_by_id)} teams from database.")
    
    # 지원하는 홈팀 ID 목록 생성 (TEAM_YOUTUBE_CHANNELS에 등록된 팀)
    supported_team_ids = []
    for english_name in TEAM_YOUTUBE_CHANNELS.keys():
        team_id = team_id_by_name.get(english_name)
        if team_id:
            supported_team_ids.append(team_id)
    
    print(f"Supported home teams: {supported_team_ids}")
    
    # 곧 시작할 경기 조회
    upcoming_games = get_upcoming_games(supported_team_ids)
    
    if not upcoming_games:
        print("No upcoming games without live_url. Exiting.")
        return
    
    print(f"Found {len(upcoming_games)} games to check.")
    
    updated_count = 0
    
    for game in upcoming_games:
        game_no = game['game_no']
        home_team_id = game['home_alih_team_id']
        away_team_id = game['away_alih_team_id']
        
        home_info = team_by_id.get(home_team_id, {})
        away_info = team_by_id.get(away_team_id, {})
        
        home_name = home_info.get('name', f'Team {home_team_id}')
        away_name = away_info.get('name', f'Team {away_team_id}')
        home_english_name = home_info.get('english_name', '')
        
        print(f"\n[Game {game_no}] {home_name} vs {away_name}")
        print(f"  Match at: {game['match_at']}")
        
        # 홈팀 채널 정보 가져오기
        channel_info = TEAM_YOUTUBE_CHANNELS.get(home_english_name)
        if not channel_info:
            print(f"  [SKIP] No channel configured for home team: {home_english_name}")
            continue
        
        channel_url = channel_info['channel_url']
        print(f"  Searching channel: {channel_url}")
        
        # 라이브 스트림 검색
        streams = find_live_streams(channel_url)
        
        if not streams:
            print(f"  [INFO] No streams found on channel")
            continue
        
        print(f"  Found {len(streams)} streams")
        
        # 경기와 매칭
        live_url = match_stream_to_game(streams, game, team_by_id)
        
        if live_url:
            # live_url 업데이트
            if update_live_url(game['id'], live_url):
                print(f"  [SUCCESS] Updated live_url: {live_url}")
                updated_count += 1
            else:
                print(f"  [FAIL] Failed to update database")
        else:
            print(f"  [INFO] No matching stream found")
            # 스트림 제목 출력 (디버깅용)
            for stream in streams[:3]:
                print(f"    - {stream['title'][:60]}...")
    
    print(f"\n[DONE] Updated {updated_count} games with live URLs.")


if __name__ == "__main__":
    main()
