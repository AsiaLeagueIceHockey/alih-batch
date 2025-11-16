import os
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client

# 1. Supabase 클라이언트 초기화
# GitHub Actions Secrets에서 환경 변수를 가져옵니다.
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 2. 팀 이름 매핑
# HTML의 팀 이름과 DB('alih_teams')의 'english_name'을 매핑합니다.
HTML_TO_DB_TEAM_MAP = {
    "HL ANYANG ICE HOCKEY CLUB": "HL Anyang",
    "RED EAGLES HOKKAIDO": "RED EAGLES HOKKAIDO",
    "NIKKO ICEBUCKS": "NIKKO ICEBUCKS",
    "YOKOHAMA GRITS": "YOKOHAMA GRITS",
    "TOHOKU FREEBLADES": "TOHOKU FREE BLADES",
    "STARS KOBE": "STARS KOBE"
}

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
    ALH_STANDINGS_URL = "https://www.alhockey.com/popup/47/standings.html"
    
    try:
        response = requests.get(ALH_STANDINGS_URL)
        # 중요: 페이지 인코딩을 'shift_jis'로 설정
        response.encoding = 'shift_jis'
        html_content = response.text
    except requests.RequestException as e:
        print(f"Error fetching URL: {e}")
        return

    soup = BeautifulSoup(html_content, 'html.parser')

    # 'RK'라는 텍스트를 가진 <th> 태그를 찾아 해당 테이블을 특정합니다.
    rk_header = soup.find('th', string='RK')
    if not rk_header:
        print("Error: Could not find standings table (RK header not found).")
        return

    standings_table = rk_header.find_parent('table')
    
    # DB의 팀 ID 맵 가져오기
    team_id_map = get_team_id_map()
    if team_id_map is None:
        print("Aborting due to error in fetching team map.")
        return

    standings_data_to_upsert = []
    
    # 테이블의 모든 <tr>(행)을 순회 (헤더 제외)
    # HTML에 <tbody>가 없으므로 <table> 바로 아래 <tr>을 찾습니다.
    for row in standings_table.find_all('tr'):
        if row.find('th'):  # 헤더 행(<th>가 있는 행) 건너뛰기
            continue

        cols = row.find_all('td')
        if not cols or len(cols) < 11: # 유효한 데이터 행인지 확인
            continue
            
        try:
            # 1. HTML에서 팀 이름 파싱
            html_team_name = cols[1].text.strip()
            
            # 2. DB 'english_name'으로 변환
            db_team_name = HTML_TO_DB_TEAM_MAP.get(html_team_name)
            if not db_team_name:
                print(f"Warning: No DB mapping for team '{html_team_name}'. Skipping.")
                continue
                
            # 3. 'team_id' 조회
            team_id = team_id_map.get(db_team_name)
            if not team_id:
                print(f"Warning: No team_id found for '{db_team_name}' in 'alih_teams'. Skipping.")
                continue

            # 4. GF - GA (골득실) 파싱
            gf_ga = cols[9].text.strip().split(' - ')
            goals_for = int(gf_ga[0])
            goals_against = int(gf_ga[1])

            # 5. Supabase에 저장할 데이터 객체 생성
            data_row = {
                'team_id': team_id,
                'rank': int(cols[0].text.strip()),
                'games_played': int(cols[2].text.strip()),
                'win_60min': int(cols[3].text.strip()),
                'win_ot': int(cols[4].text.strip()),
                'win_pss': int(cols[5].text.strip()),
                'lose_pss': int(cols[6].text.strip()),
                'lose_ot': int(cols[7].text.strip()),
                'lose_60min': int(cols[8].text.strip()),
                'goals_for': goals_for,
                'goals_against': goals_against,
                'points': int(cols[10].text.strip()),
                'updated_at': 'now()' # DB에서 현재 시간으로 자동 설정
            }
            standings_data_to_upsert.append(data_row)
            
        except Exception as e:
            print(f"Error parsing row: {e} | Row data: {row.text.strip()}")

    # 6. 데이터 일괄 업서트(Upsert)
    if standings_data_to_upsert:
        print(f"Upserting {len(standings_data_to_upsert)} rows to 'alih_standings'...")
        try:
            # 'on_conflict'는 1번 단계에서 설정한 UNIQUE 제약조건(team_id)을 기준으로 합니다.
            response = supabase.table('alih_standings').upsert(
                standings_data_to_upsert,
                on_conflict='team_id'
            ).execute()
            
            print("Upsert complete.")
            if hasattr(response, 'error') and response.error:
                print(f"Supabase Error: {response.error}")
            else:
                print(f"Successfully upserted {len(response.data)} records.")

        except Exception as e:
            print(f"Error during Supabase upsert: {e}")
    else:
        print("No data parsed to upsert.")

if __name__ == "__main__":
    scrape_and_update_standings()