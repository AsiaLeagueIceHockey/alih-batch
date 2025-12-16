import os
import subprocess
import json
import re
from datetime import datetime, timedelta
from supabase import create_client, Client

# --- 1. Supabase 클라이언트 초기화 ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise EnvironmentError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 2. YouTube 팀명 -> DB 팀명 매핑 ---
# YouTube 영상 제목에서 사용되는 팀명을 DB의 english_name으로 매핑
YOUTUBE_TO_DB_TEAM_MAP = {
    "hl anyang": "HL Anyang",
    "nikko icebucks": "NIKKO ICEBUCKS",
    "tohoku freeblades": "TOHOKU FREE BLADES",
    "stars kobe": "STARS KOBE",
    "yokohama grits": "YOKOHAMA GRITS",
    "red eagles hokkaido": "RED EAGLES HOKKAIDO",
    # 추가 변형 (대소문자 무시)
    "anyang": "HL Anyang",
    "icebucks": "NIKKO ICEBUCKS",
    "freeblades": "TOHOKU FREE BLADES",
    "kobe": "STARS KOBE",
    "grits": "YOKOHAMA GRITS",
    "red eagles": "RED EAGLES HOKKAIDO",
}

def normalize_team_name(name: str) -> str:
    """YouTube 팀명을 DB 팀명으로 변환"""
    name_lower = name.lower().strip()
    
    # 직접 매핑 시도
    if name_lower in YOUTUBE_TO_DB_TEAM_MAP:
        return YOUTUBE_TO_DB_TEAM_MAP[name_lower]
    
    # 부분 매칭 시도
    for key, value in YOUTUBE_TO_DB_TEAM_MAP.items():
        if key in name_lower or name_lower in key:
            return value
    
    return name  # 매핑 실패 시 원본 반환

# --- 3. DB에서 팀 정보 맵 가져오기 ---
def get_team_maps():
    """
    팀 정보를 가져와서 두 개의 맵을 반환:
    1. english_name -> team_id
    2. team_id -> korean_name (name)
    """
    try:
        response = supabase.table('alih_teams').select('id, english_name, name').execute()
        if response.data:
            id_map = {team['english_name']: team['id'] for team in response.data}
            korean_name_map = {team['id']: team['name'] for team in response.data}
            return id_map, korean_name_map
        return {}, {}
    except Exception as e:
        print(f"Error fetching team map: {e}")
        return {}, {}

# --- 4. yt-dlp로 YouTube 채널 영상 목록 가져오기 ---
def get_recent_videos(channel_url: str, limit: int = 20) -> list:
    """
    yt-dlp를 사용하여 YouTube 채널의 최근 영상 목록을 가져옵니다.
    """
    cmd = [
        'yt-dlp',
        '--flat-playlist',
        '--dump-json',
        '--playlist-end', str(limit),
        '--no-warnings',
        channel_url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"yt-dlp error: {result.stderr}")
            return []
        
        videos = []
        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    videos.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return videos
    except subprocess.TimeoutExpired:
        print("yt-dlp command timed out")
        return []
    except Exception as e:
        print(f"Error running yt-dlp: {e}")
        return []

# --- 5. 영상 제목 파싱 ---
def parse_video_title(title: str) -> dict | None:
    """
    영상 제목에서 날짜와 팀 정보를 추출합니다.
    예: 【2025.12.14】Tohoku FreeBlades vs Stars Kobe | Asia League Highlights |
    """
    # 하이라이트 영상인지 확인
    if 'highlight' not in title.lower():
        return None
    
    # 날짜 및 팀 추출 패턴
    pattern = r'【(\d{4})\.(\d{1,2})\.(\d{1,2})】(.+?)\s+vs\s+(.+?)\s*\|'
    match = re.match(pattern, title, re.IGNORECASE)
    
    if match:
        year, month, day = match.groups()[:3]
        team_a, team_b = match.groups()[3:5]
        return {
            'date': f"{year}-{month.zfill(2)}-{day.zfill(2)}",
            'team_a': normalize_team_name(team_a),
            'team_b': normalize_team_name(team_b),
            'original_title': title
        }
    
    return None

# --- 6. 하이라이트 타이틀 생성 ---
def generate_highlight_title(parsed_info: dict, home_team_id: int, away_team_id: int, korean_name_map: dict) -> str:
    """
    하이라이트 타이틀을 생성합니다.
    형식: 하이라이트 | 홈팀 한국어 vs 어웨이팀 한국어 | 2025.12.13
    """
    # 날짜 형식 변환 (2025-12-13 -> 2025.12.13)
    date_str = parsed_info['date'].replace('-', '.')
    
    # 한국어 팀명 가져오기
    home_korean = korean_name_map.get(home_team_id, parsed_info['team_a'])
    away_korean = korean_name_map.get(away_team_id, parsed_info['team_b'])
    
    return f"하이라이트 | {home_korean} vs {away_korean} | {date_str}"

# --- 7. 경기 매칭 및 업데이트 ---
def match_and_update_schedule(video: dict, parsed_info: dict, team_id_map: dict, korean_name_map: dict):
    """
    파싱된 영상 정보를 alih_schedule과 매칭하여 업데이트합니다.
    """
    match_date = parsed_info['date']
    team_a = parsed_info['team_a']
    team_b = parsed_info['team_b']
    
    team_a_id = team_id_map.get(team_a)
    team_b_id = team_id_map.get(team_b)
    
    if not team_a_id or not team_b_id:
        print(f"  [SKIP] Team not found in DB: {team_a} or {team_b}")
        return False
    
    # 해당 날짜에 두 팀이 맞붙은 경기 검색
    # match_at은 timestamp이므로 날짜 범위로 검색
    date_start = f"{match_date}T00:00:00"
    date_end = f"{match_date}T23:59:59"
    
    try:
        # OR 조건: (home=A, away=B) OR (home=B, away=A)
        response = supabase.table('alih_schedule') \
            .select('id, game_no, home_alih_team_id, away_alih_team_id, highlight_url') \
            .gte('match_at', date_start) \
            .lte('match_at', date_end) \
            .execute()
        
        if not response.data:
            print(f"  [SKIP] No games found on {match_date}")
            return False
        
        # 팀 매칭
        matched_game = None
        for game in response.data:
            home_id = game['home_alih_team_id']
            away_id = game['away_alih_team_id']
            
            # 홈/어웨이 순서 상관없이 매칭
            if (home_id == team_a_id and away_id == team_b_id) or \
               (home_id == team_b_id and away_id == team_a_id):
                matched_game = game
                break
        
        if not matched_game:
            print(f"  [SKIP] No matching game for {team_a} vs {team_b} on {match_date}")
            return False
        
        # 이미 하이라이트가 있는지 확인
        if matched_game.get('highlight_url'):
            print(f"  [SKIP] Game {matched_game['game_no']} already has highlight")
            return False
        
        # 업데이트
        video_url = f"https://www.youtube.com/watch?v={video['id']}"
        
        # 홈/어웨이 팀 ID 확인
        home_team_id = matched_game['home_alih_team_id']
        away_team_id = matched_game['away_alih_team_id']
        
        # 한국어 타이틀 생성
        highlight_title = generate_highlight_title(parsed_info, home_team_id, away_team_id, korean_name_map)
        
        update_response = supabase.table('alih_schedule') \
            .update({
                'highlight_url': video_url,
                'highlight_title': highlight_title
            }) \
            .eq('id', matched_game['id']) \
            .execute()
        
        print(f"  [SUCCESS] Updated Game {matched_game['game_no']}: {highlight_title}")
        return True
        
    except Exception as e:
        print(f"  [ERROR] Database error: {e}")
        return False

# --- 8. 메인 함수 ---
def main():
    print(f"[{datetime.now().isoformat()}] Starting YouTube highlights scraper...")
    
    channel_url = "https://www.youtube.com/@ALhockey_JP/videos"
    
    # 팀 정보 맵 가져오기
    team_id_map, korean_name_map = get_team_maps()
    if not team_id_map:
        print("Failed to load team maps. Exiting.")
        return
    
    print(f"Loaded {len(team_id_map)} teams from database.")
    
    # 최근 영상 가져오기
    print(f"Fetching recent videos from {channel_url}...")
    videos = get_recent_videos(channel_url, limit=30)
    
    if not videos:
        print("No videos found. Exiting.")
        return
    
    print(f"Found {len(videos)} videos. Processing...")
    
    updated_count = 0
    
    for video in videos:
        title = video.get('title', '')
        print(f"\nProcessing: {title[:60]}...")
        
        parsed = parse_video_title(title)
        if not parsed:
            print("  [SKIP] Not a highlight video or failed to parse")
            continue
        
        print(f"  Parsed: {parsed['date']} - {parsed['team_a']} vs {parsed['team_b']}")
        
        if match_and_update_schedule(video, parsed, team_id_map, korean_name_map):
            updated_count += 1
    
    print(f"\n[DONE] Updated {updated_count} games with highlights.")

if __name__ == "__main__":
    main()
