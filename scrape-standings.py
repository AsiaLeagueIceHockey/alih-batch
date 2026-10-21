import os
import requests
from datetime import datetime, timezone
from supabase import create_client, Client
from season_config import require_target_season, write_enabled
from standings_parser import parse_standings_html

# 1. Supabase 클라이언트 초기화
# GitHub Actions Secrets에서 환경 변수를 가져옵니다.
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TARGET_SEASON = require_target_season()
SOURCE_POPUP_ID = os.environ.get("SOURCE_POPUP_ID", "49")
WRITE_ENABLED = write_enabled()

if not SUPABASE_URL or not SUPABASE_KEY:
    raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_team_id_map():
    """
    'alih_teams' 테이블에서 'english_name'을 key로, 'id'를 value로 하는 맵을 생성합니다.
    e.g. {'HL Anyang': 1, 'RED EAGLES HOKKAIDO': 2, ...}
    """
    try:
        response = supabase.table('alih_teams').select('id, english_name').execute()
        if response.data:
            return {team['english_name']: team['id'] for team in response.data}
        return {}
    except Exception as e:
        print(f"Error fetching team map from Supabase: {e}")
        return None

def scrape_and_update_standings():
    """
    순위표 페이지를 스크래핑하고 Supabase에 데이터를 업서트(Upsert)합니다.
    """
    ALH_STANDINGS_URL = f"https://www.alhockey.com/popup/{SOURCE_POPUP_ID}/standings.html"
    
    try:
        response = requests.get(ALH_STANDINGS_URL, timeout=20)
        response.raise_for_status()
        # 중요: 페이지 인코딩을 'shift_jis'로 설정
        response.encoding = 'shift_jis'
        html_content = response.text
    except requests.RequestException as e:
        raise RuntimeError(f"Error fetching official standings: {e}") from e

    # DB의 팀 ID 맵 가져오기
    team_id_map = get_team_id_map()
    if team_id_map is None:
        raise RuntimeError("Could not fetch the alih_teams identity map")

    standings_data_to_upsert = parse_standings_html(
        html_content,
        TARGET_SEASON,
        team_id_map,
        datetime.now(timezone.utc).isoformat(),
    )

    if not WRITE_ENABLED:
        print(f"[DRY RUN] Validated {len(standings_data_to_upsert)} official active-team standings rows for {TARGET_SEASON}")
        return
    print(f"Upserting {len(standings_data_to_upsert)} rows to 'alih_standings'...")
    try:
        response = supabase.table('alih_standings').upsert(
            standings_data_to_upsert,
            on_conflict='team_id,season'
        ).execute()

        print("Upsert complete.")
        if hasattr(response, 'error') and response.error:
            raise RuntimeError(f"Supabase error: {response.error}")
        print(f"Successfully upserted {len(response.data)} records.")
    except Exception as e:
        raise RuntimeError(f"Error during Supabase upsert: {e}") from e

if __name__ == "__main__":
    scrape_and_update_standings()
