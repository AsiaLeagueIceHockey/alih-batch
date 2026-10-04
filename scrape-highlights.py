import os
import subprocess
import json
from datetime import datetime
from supabase import create_client, Client
from highlight_parser import (
    highlight_match_key,
    highlight_video_priority,
    parse_video_title,
)
from season_config import require_target_season, write_enabled

# --- 1. Supabase 클라이언트 초기화 ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
TARGET_SEASON = require_target_season()
WRITE_ENABLED = write_enabled()

if not SUPABASE_URL or not SUPABASE_KEY:
    raise EnvironmentError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

HIGHLIGHT_SOURCES = [
    {
        "name": "ALHockey_JP",
        "channel_url": "https://www.youtube.com/@ALhockey_JP/videos",
        "limit": 80,
    },
    {
        "name": "ON_THE_SPORTS",
        "channel_url": "https://www.youtube.com/channel/UC-JEIp-IjHJJ8g3812Z7MUw/videos",
        "limit": 80,
    },
]

# --- 3. DB에서 팀 정보 맵 가져오기 ---
def get_team_maps():
    """
    팀 정보를 가져와서 두 개의 맵을 반환:
    1. english_name (소문자) -> team_id
    2. team_id -> korean_name (name)
    """
    try:
        response = supabase.table('alih_teams').select('id, english_name, name').execute()
        if response.data:
            # 소문자로 정규화하여 저장
            id_map = {team['english_name'].lower(): team['id'] for team in response.data}
            korean_name_map = {team['id']: team['name'] for team in response.data}
            print(f"DEBUG: Team ID map keys: {list(id_map.keys())}")
            return id_map, korean_name_map
        return {}, {}
    except Exception as e:
        print(f"Error fetching team map: {e}")
        return {}, {}

# --- 4. yt-dlp로 YouTube 채널 영상 목록 가져오기 ---
def get_recent_videos(channel_url: str, limit: int = 20) -> list | None:
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
            return None
        
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
        return None
    except Exception as e:
        print(f"Error running yt-dlp: {e}")
        return None

# --- 5. 하이라이트 타이틀 생성 ---
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

# --- 6. 경기 매칭 및 업데이트 ---
def match_and_update_schedule(video: dict, parsed_info: dict, team_id_map: dict, korean_name_map: dict):
    """
    파싱된 영상 정보를 alih_schedule과 매칭하여 업데이트합니다.
    """
    match_date = parsed_info['date']
    team_a = parsed_info['team_a']
    team_b = parsed_info['team_b']
    
    # 소문자로 정규화하여 조회
    team_a_id = team_id_map.get(team_a.lower())
    team_b_id = team_id_map.get(team_b.lower())
    
    if not team_a_id or not team_b_id:
        print(f"  [SKIP] Team not found in DB: {team_a} or {team_b}")
        return "unknown_team"
    
    # 해당 날짜에 두 팀이 맞붙은 경기 검색
    # match_at은 timestamp이므로 날짜 범위로 검색
    date_start = f"{match_date}T00:00:00+09:00"
    date_end = f"{match_date}T23:59:59+09:00"
    
    try:
        # OR 조건: (home=A, away=B) OR (home=B, away=A)
        response = supabase.table('alih_schedule') \
            .select('id, game_no, home_alih_team_id, away_alih_team_id, highlight_url') \
            .eq('season', TARGET_SEASON) \
            .gte('match_at', date_start) \
            .lte('match_at', date_end) \
            .execute()
        
        if not response.data:
            print(f"  [SKIP] No games found on {match_date}")
            return "no_game"
        
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
            return "no_game"
        
        # 이미 하이라이트가 있는지 확인
        if matched_game.get('highlight_url'):
            print(f"  [SKIP] Game {matched_game['game_no']} already has highlight")
            return "existing"
        
        # 업데이트
        video_url = f"https://www.youtube.com/watch?v={video['id']}"
        
        home_team_id = matched_game['home_alih_team_id']
        away_team_id = matched_game['away_alih_team_id']

        highlight_title = generate_highlight_title(parsed_info, home_team_id, away_team_id, korean_name_map)

        if not WRITE_ENABLED:
            print(f"  [DRY RUN] Would update Game {matched_game['game_no']}: {highlight_title}")
            return "would_update"

        
        update_response = supabase.table('alih_schedule') \
            .update({
                'highlight_url': video_url,
                'highlight_title': highlight_title
            }) \
            .eq('id', matched_game['id']) \
            .execute()

        if not update_response.data or not any(
            row.get('id') == matched_game['id'] for row in update_response.data
        ):
            print(f"  [ERROR] Update for Game {matched_game['game_no']} returned no matching row")
            return "error"
        
        print(f"  [SUCCESS] Updated Game {matched_game['game_no']}: {highlight_title}")
        return "updated"
        
    except Exception as e:
        print(f"  [ERROR] Database error: {e}")
        return "error"

# --- 7. 메인 함수 ---
def main():
    print(f"[{datetime.now().isoformat()}] Starting YouTube highlights scraper...")

    # 팀 정보 맵 가져오기
    team_id_map, korean_name_map = get_team_maps()
    if not team_id_map:
        print("Failed to load team maps. Exiting.")
        raise SystemExit(1)
    
    print(f"Loaded {len(team_id_map)} teams from database.")

    result_counts = {
        "updated": 0,
        "would_update": 0,
        "existing": 0,
        "no_game": 0,
        "unknown_team": 0,
        "unparsed": 0,
        "duplicate": 0,
        "error": 0,
    }
    seen_video_ids = set()
    seen_matches = set()

    for source in HIGHLIGHT_SOURCES:
        channel_url = source['channel_url']
        limit = source['limit']

        print(f"\nFetching recent videos from {source['name']} ({channel_url})...")
        videos = get_recent_videos(channel_url, limit=limit)

        if videos is None:
            print("  [ERROR] Failed to fetch this source")
            result_counts["error"] += 1
            continue

        if not videos:
            print("  [WARN] No videos found for this source")
            continue

        print(f"Found {len(videos)} videos. Processing...")

        # The official channel sometimes publishes an all-goals derivative
        # before the normal highlight. Process the canonical highlight first.
        for video in sorted(videos, key=highlight_video_priority):
            video_id = video.get('id')
            if video_id and video_id in seen_video_ids:
                continue

            if video_id:
                seen_video_ids.add(video_id)

            title = video.get('title', '')
            print(f"\nProcessing: {title[:80]}...")

            parsed = parse_video_title(title)
            if not parsed:
                print("  [SKIP] Not a supported highlight title or failed to parse")
                result_counts["unparsed"] += 1
                continue

            print(f"  Parsed: {parsed['date']} - {parsed['team_a']} vs {parsed['team_b']}")

            match_key = highlight_match_key(parsed)
            if match_key in seen_matches:
                print("  [SKIP] A preferred video was already processed for this matchup")
                result_counts["duplicate"] += 1
                continue

            seen_matches.add(match_key)
            result = match_and_update_schedule(video, parsed, team_id_map, korean_name_map)
            result_counts[result] += 1
    
    mode = "WRITE" if WRITE_ENABLED else "DRY RUN"
    print(
        f"\n[DONE] mode={mode} updated={result_counts['updated']} "
        f"would_update={result_counts['would_update']} existing={result_counts['existing']} "
        f"no_game={result_counts['no_game']} unknown_team={result_counts['unknown_team']} "
        f"unparsed={result_counts['unparsed']} duplicate={result_counts['duplicate']} "
        f"errors={result_counts['error']}"
    )

    if result_counts["error"]:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
