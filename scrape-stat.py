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

def get_team_code_map():
    """
    DB에서 team_code(예: 'HLA')를 키로, id를 값으로 하는 맵을 가져옵니다.
    """
    try:
        # alih_teams 테이블에 team_code 컬럼이 있어야 합니다.
        response = supabase.table('alih_teams').select('id, team_code').execute()
        if response.data:
            # 공백 제거 등 전처리
            return {team['team_code'].strip(): team['id'] for team in response.data if team['team_code']}
        return {}
    except Exception as e:
        print(f"Error fetching team map: {e}")
        return {}

def parse_rank_table(soup, header_text, data_type, players_dict, team_code_map):
    """
    특정 헤더(header_text)를 가진 테이블을 찾아 players_dict에 데이터를 병합합니다.
    data_type: 'goals', 'assists', 'points' 중 하나
    """
    # 1. 헤더 찾기 (예: "Goal Ranking")
    # HTML 구조상 <th>Goal Ranking </th> 처럼 되어 있음
    header_th = soup.find('th', string=lambda t: t and header_text in t)
    if not header_th:
        print(f"Warning: Header '{header_text}' not found.")
        return

    # 2. 해당 헤더가 있는 큰 테이블의 구조를 따라가서 데이터 테이블 찾기
    # 구조: <tr><th>Goal Ranking</th>...</tr> <tr><td><table>...</table></td>...</tr>
    # 헤더의 부모 tr의 다음 형제 tr을 찾고, 그 안에서 인덱스에 맞는 td 안의 table을 찾아야 함
    
    # 간단하게 접근: 해당 헤더 텍스트가 포함된 th의 인덱스를 찾음
    header_row = header_th.find_parent('tr')
    headers = header_row.find_all('th')
    target_index = headers.index(header_th)
    
    data_row = header_row.find_next_sibling('tr')
    data_tds = data_row.find_all('td', recursive=False) # 바로 아래 자식만
    
    if len(data_tds) <= target_index:
        print(f"Error: Table structure mismatch for {header_text}")
        return

    target_td = data_tds[target_index]
    target_table = target_td.find('table')
    
    if not target_table:
        print(f"Error: Inner table not found for {header_text}")
        return

    # 3. 행 파싱
    rows = target_table.find_all('tr')
    for row in rows:
        # 헤더 행(bgcolor="#CCCCCC") 스킵
        if row.get('bgcolor') == '#CCCCCC' or row.find('th'):
            continue
            
        cols = row.find_all('td')
        if len(cols) < 5:
            continue

        try:
            rank = int(cols[0].text.strip())
            name = cols[1].text.strip()
            number = int(cols[2].text.strip())
            team_code = cols[3].text.strip()
            value = int(cols[4].text.strip()) # G, A, or P

            # DB team_id 찾기
            team_id = team_code_map.get(team_code)
            if not team_id:
                print(f"Skipping {name}: Unknown team code '{team_code}'")
                continue

            # 고유 키: (team_id, player_name)
            player_key = (team_id, name)

            if player_key not in players_dict:
                players_dict[player_key] = {
                    "team_id": team_id,
                    "player_name": name,
                    "jersey_number": number,
                    "goals": 0,
                    "assists": 0,
                    "points": 0,
                    "goals_rank": None,
                    "assists_rank": None,
                    "points_rank": None
                }
            
            # 데이터 병합
            if data_type == 'goals':
                players_dict[player_key]['goals'] = value
                players_dict[player_key]['goals_rank'] = rank
            elif data_type == 'assists':
                players_dict[player_key]['assists'] = value
                players_dict[player_key]['assists_rank'] = rank
            elif data_type == 'points':
                players_dict[player_key]['points'] = value
                players_dict[player_key]['points_rank'] = rank

        except ValueError as ve:
            continue # 데이터 포맷 에러 시 해당 행 무시
        except Exception as e:
            print(f"Error parsing row in {header_text}: {e}")

def scrape_and_upsert_player_stats():
    URL = "https://www.alhockey.com/popup/47/point_rank.html"
    
    try:
        response = requests.get(URL)
        response.encoding = 'shift_jis' # 필수 인코딩 설정
        html = response.text
    except Exception as e:
        print(f"Network Error: {e}")
        return

    soup = BeautifulSoup(html, 'html.parser')
    
    team_code_map = get_team_code_map()
    if not team_code_map:
        print("Failed to load team codes from DB.")
        return

    # 모든 데이터를 모을 딕셔너리
    # Key: (team_id, player_name), Value: Data Dict
    players_dict = {}

    # 3개의 랭킹 테이블 파싱 및 병합
    print("Parsing Goal Ranking...")
    parse_rank_table(soup, "Goal Ranking", "goals", players_dict, team_code_map)
    
    print("Parsing Assist Ranking...")
    parse_rank_table(soup, "Assist Ranking", "assists", players_dict, team_code_map)
    
    print("Parsing Points Ranking...")
    parse_rank_table(soup, "Points Ranking", "points", players_dict, team_code_map)

    # 데이터 리스트로 변환
    upsert_data = [
        {**data, "updated_at": "now()"} 
        for data in players_dict.values()
    ]

    if upsert_data:
        print(f"Upserting {len(upsert_data)} player records...")
        try:
            # team_id와 player_name이 Unique Constraint여야 함
            result = supabase.table('alih_player_stats').upsert(
                upsert_data, 
                on_conflict='team_id, player_name'
            ).execute()
            print("Upsert Complete.")
        except Exception as e:
            print(f"Supabase Error: {e}")
    else:
        print("No data found to upsert.")

if __name__ == "__main__":
    scrape_and_upsert_player_stats()