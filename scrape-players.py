import os
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client

# 1. Supabase 설정
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 2. 팀 이름 매핑 (HTML의 팀명 -> DB의 english_name)
# 주의: TOHOKU FREEBLADES 띄어쓰기 이슈 반영
HTML_TO_DB_TEAM_MAP = {
    "HL ANYANG ICE HOCKEY CLUB": "HL Anyang",
    "RED EAGLES HOKKAIDO": "RED EAGLES HOKKAIDO",
    "NIKKO ICEBUCKS": "NIKKO ICEBUCKS",
    "YOKOHAMA GRITS": "YOKOHAMA GRITS",
    "TOHOKU FREEBLADES": "TOHOKU FREE BLADES", 
    "STARS KOBE": "STARS KOBE"
}

def get_team_id_map():
    """DB에서 팀 ID 맵 가져오기"""
    try:
        response = supabase.table('alih_teams').select('id, english_name').execute()
        if response.data:
            return {team['english_name']: team['id'] for team in response.data}
        return {}
    except Exception as e:
        print(f"Error fetching team map: {e}")
        return None

def parse_int(text):
    """문자열을 안전하게 정수로 변환"""
    try:
        return int(text.strip())
    except ValueError:
        return 0

def scrape_and_update_players():
    url = "https://www.alhockey.com/popup/47/individual.html"
    
    try:
        response = requests.get(url)
        response.encoding = 'shift_jis' # 인코딩 설정 필수
        html = response.text
    except Exception as e:
        print(f"Failed to fetch URL: {e}")
        return

    soup = BeautifulSoup(html, 'html.parser')
    
    # DB 팀 정보 가져오기
    team_id_map = get_team_id_map()
    if not team_id_map:
        return

    players_to_upsert = []

    # span class="style3"가 포함된 모든 tr을 찾음 (팀 이름 헤더 행)
    team_headers = soup.find_all('span', class_='style3')
    
    print(f"Found {len(team_headers)} teams in HTML.")

    for team_span in team_headers:
        html_team_name = team_span.text.strip()
        
        # DB 매핑 확인
        db_team_name = HTML_TO_DB_TEAM_MAP.get(html_team_name)
        if not db_team_name:
            print(f"Skipping unknown team in HTML: {html_team_name}")
            continue
            
        team_id = team_id_map.get(db_team_name)
        if not team_id:
            print(f"Skipping team not found in DB: {db_team_name}")
            continue

        # 현재 span의 부모(td) -> 부모(tr) -> 부모(table) 찾기
        # 구조: table > tr > td > span.style3
        current_table = team_span.find_parent('table')
        
        # 테이블 내의 모든 행(tr) 순회
        rows = current_table.find_all('tr')
        
        for row in rows:
            cols = row.find_all('td')
            
            # 데이터 행은 보통 13개의 컬럼을 가짐 (No, Name, POS, GP ... GM)
            # 헤더나 팀 이름 행은 건너뜀
            if len(cols) < 13:
                continue
            
            # 헤더 행인지 확인 (첫 컬럼이 'No.'이면 스킵)
            if "No." in cols[0].text:
                continue

            try:
                # 데이터 추출
                # 0: No, 1: Name, 2: POS, 3: GP, 4: PTS, 5: G, 6: A, 7: S, 8: SG, 9: +/-, 10: PIM ...
                
                player_data = {
                    "team_id": team_id,
                    "jersey_number": parse_int(cols[0].text),
                    "name": cols[1].text.strip(),
                    "position": cols[2].text.strip(),
                    "games_played": parse_int(cols[3].text),
                    "points": parse_int(cols[4].text),
                    "goals": parse_int(cols[5].text),
                    "assists": parse_int(cols[6].text),
                    "shots": parse_int(cols[7].text),
                    "plus_minus": cols[9].text.strip(), # "4/2" 형태 유지
                    "pim": parse_int(cols[10].text),
                    "updated_at": "now()"
                }
                
                players_to_upsert.append(player_data)
                
            except Exception as e:
                print(f"Error parsing player row: {e}")
                continue

    # Supabase 저장
    if players_to_upsert:
        print(f"Upserting {len(players_to_upsert)} players...")
        try:
            # team_id와 name을 기준으로 업데이트 (unique constraints 필요)
            result = supabase.table('alih_players').upsert(
                players_to_upsert, 
                on_conflict='team_id, name'
            ).execute()
            print("Success!")
        except Exception as e:
            print(f"Supabase Error: {e}")
    else:
        print("No players found.")

if __name__ == "__main__":
    scrape_and_update_players()