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
        response = supabase.table('alih_teams').select('id, team_code').execute()
        if response.data:
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
    header_th = soup.find('th', string=lambda t: t and header_text in t)
    if not header_th:
        print(f"Warning: Header '{header_text}' not found.")
        return

    header_row = header_th.find_parent('tr')
    headers = header_row.find_all('th')
    target_index = headers.index(header_th)
    
    data_row = header_row.find_next_sibling('tr')
    data_tds = data_row.find_all('td', recursive=False) 
    
    if len(data_tds) <= target_index:
        return

    target_td = data_tds[target_index]
    target_table = target_td.find('table')
    
    if not target_table:
        return

    rows = target_table.find_all('tr')
    for row in rows:
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

            team_id = team_code_map.get(team_code)
            if not team_id:
                print(f"Skipping {name}: Unknown team code '{team_code}'")
                continue

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
            
            if data_type == 'goals':
                players_dict[player_key]['goals'] = value
                players_dict[player_key]['goals_rank'] = rank
            elif data_type == 'assists':
                players_dict[player_key]['assists'] = value
                players_dict[player_key]['assists_rank'] = rank
            elif data_type == 'points':
                players_dict[player_key]['points'] = value
                players_dict[player_key]['points_rank'] = rank

        except ValueError:
            continue 
        except Exception as e:
            print(f"Error parsing row in {header_text}: {e}")

def scrape_and_upsert_player_stats():
    URL = "https://www.alhockey.com/popup/47/point_rank.html"
    
    try:
        response = requests.get(URL)
        response.encoding = 'shift_jis' 
        html = response.text
    except Exception as e:
        print(f"Network Error: {e}")
        return

    soup = BeautifulSoup(html, 'html.parser')
    
    team_code_map = get_team_code_map()
    if not team_code_map:
        print("Failed to load team codes from DB.")
        return

    players_dict = {}

    print("Parsing Goal Ranking...")
    parse_rank_table(soup, "Goal Ranking", "goals", players_dict, team_code_map)
    
    print("Parsing Assist Ranking...")
    parse_rank_table(soup, "Assist Ranking", "assists", players_dict, team_code_map)
    
    print("Parsing Points Ranking...")
    parse_rank_table(soup, "Points Ranking", "points", players_dict, team_code_map)

    # ---------------------------------------------------------
    # [핵심 수정] 데이터 상호 보정 로직 (Cross-Validation)
    # Goals + Assists = Points 공식을 이용하여 누락된 데이터를 채웁니다.
    # ---------------------------------------------------------
    print("Validating and correcting stats (G + A = P)...")
    
    for key, data in players_dict.items():
        g = data['goals']
        a = data['assists']
        p = data['points']

        # CASE 1: 포인트 랭킹 데이터가 더 큼 (구성 요소 누락)
        # 예: G=12, A=0, P=17 -> A 누락 -> A = 17 - 12 = 5
        if p > (g + a):
            # 골은 있는데 어시스트가 없는 경우
            if g > 0 and a == 0:
                data['assists'] = p - g
            # 어시스트는 있는데 골이 없는 경우
            elif a > 0 and g == 0:
                data['goals'] = p - a
            
            # 수정된 값을 다시 반영
            g = data['goals']
            a = data['assists']

        # CASE 2: 구성 요소의 합이 포인트보다 큼 (포인트 랭킹 누락/업데이트 지연)
        # 예: G=0, A=6, P=0 -> P 누락 -> P = 0 + 6 = 6
        current_sum = g + a
        if current_sum > p:
            data['points'] = current_sum

    upsert_data = [
        {**data, "updated_at": "now()"} 
        for data in players_dict.values()
    ]

    if upsert_data:
        print(f"Upserting {len(upsert_data)} player records...")
        try:
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