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
# DB english_name: HL ANYANG, EAGLES, FREEBLADES, GRITS, ICEBUCKS, STARS
HTML_TO_DB_TEAM_MAP = {
    "HL ANYANG ICE HOCKEY CLUB": "HL ANYANG",
    "RED EAGLES HOKKAIDO": "EAGLES",
    "NIKKO ICEBUCKS": "ICEBUCKS",
    "YOKOHAMA GRITS": "GRITS",
    "TOHOKU FREEBLADES": "FREEBLADES", 
    "STARS KOBE": "STARS"
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

# 3. 팀 약어 매핑 (HTML의 약어 -> DB의 english_name)
CODE_TO_DB_TEAM_MAP = {
    "HLA": "HL ANYANG",
    "REH": "EAGLES",
    "NIB": "ICEBUCKS",
    "YGR": "GRITS",
    "TFB": "FREEBLADES",
    "SKB": "STARS"
}

def get_player_lookup_map(team_id_map):
    """
    모든 선수를 가져와서 (team_id, jersey_number) -> name 매핑 생성
    GK 데이터에 이름이 다르게 표기될 경우(공백 등)를 대비해 등번호로 매칭
    """
    try:
        # 필요한 필드만 조회
        response = supabase.table('alih_players').select('team_id, jersey_number, name').execute()
        player_map = {}
        if response.data:
            for p in response.data:
                key = (p['team_id'], p['jersey_number'])
                player_map[key] = p['name']
        return player_map
    except Exception as e:
        print(f"Error fetching player map: {e}")
        return {}

def scrape_and_update_goalies():
    """골리 스탯 별도 스크래핑"""
    print("\nStarting Goalie Stats Scraping...")
    url = "https://www.alhockey.com/popup/47/gksp.html"
    
    try:
        response = requests.get(url)
        response.encoding = 'shift_jis'
        html = response.text
    except Exception as e:
        print(f"Failed to fetch GK URL: {e}")
        return

    soup = BeautifulSoup(html, 'html.parser')
    
    team_id_map = get_team_id_map()
    if not team_id_map:
        return

    # (team_id, jersey_number) -> name 매핑 가져오기
    player_lookup = get_player_lookup_map(team_id_map)
    
    goalies_to_upsert = []
    
    # 데이터 테이블 찾기 (border=1 속성을 가진 테이블)
    tables = soup.find_all('table', attrs={'border': '1'})
    if not tables:
        print("GK table not found.")
        return
        
    # 보통 첫번째 border=1 테이블이 데이터 테이블임
    target_table = tables[0]
    rows = target_table.find_all('tr')
    
    for row in rows:
        cols = row.find_all('td')
        
        # 헤더나 구분선 등은 스킵
        if not cols or len(cols) < 12:
            continue
            
        # 헤더 행 스킵 (첫 컬럼이 'RK')
        if "RK" in cols[0].text:
            continue

        try:
            # 0: RK, 1: Name, 2: Team, 3: No, 4: GP, 5: Time, 6: SAG, 7: G, 8: SSG, 9: SSG%, 10: GAA, 11: GKC
            name_raw = cols[1].text.strip()
            team_code = cols[2].text.strip()
            jersey_number = parse_int(cols[3].text)
            
            db_team_name = CODE_TO_DB_TEAM_MAP.get(team_code)
            if not db_team_name:
                print(f"Unknown team code: {team_code}")
                continue
                
            team_id = team_id_map.get(db_team_name)
            if not team_id:
                continue
                
            # 등번호로 기존 선수 이름 찾기
            db_name = player_lookup.get((team_id, jersey_number))
            
            if not db_name:
                print(f"Warning: Goalie not found in regular player list: {name_raw} ({team_code} #{jersey_number})")
                db_name = name_raw

            goalie_data = {
                "team_id": team_id,
                "name": db_name, # 중요: DB에 있는 이름으로 업데이트해야 upsert가 됨
                
                # GK Stats
                "play_time": cols[5].text.strip(),
                "shots_against": parse_int(cols[6].text),      # SAG
                "goals_against": parse_int(cols[7].text),      # G
                "saves": parse_int(cols[8].text),              # SSG
                
                # float 변환
                "save_pct": float(cols[9].text.strip()) if cols[9].text.strip() else 0.0,
                "goals_against_average": float(cols[10].text.strip()) if cols[10].text.strip() else 0.0,
                "gkc": float(cols[11].text.strip()) if cols[11].text.strip() else 0.0,
                
                "updated_at": "now()"
            }
            
            goalies_to_upsert.append(goalie_data)

        except Exception as e:
            print(f"Error parsing goalie row: {e}")
            continue

    if goalies_to_upsert:
        print(f"Upserting {len(goalies_to_upsert)} goalies stats...")
        try:
            # name과 team_id가 일치하는 행에 해당 컬럼들만 업데이트
            result = supabase.table('alih_players').upsert(
                goalies_to_upsert, 
                on_conflict='team_id, name'
            ).execute()
            print("GK Stats Success!")
        except Exception as e:
            print(f"Supabase Output: {e}")
    else:
        print("No goalies found.")

if __name__ == "__main__":
    scrape_and_update_players()
    scrape_and_update_goalies()