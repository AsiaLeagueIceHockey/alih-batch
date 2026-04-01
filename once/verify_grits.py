import os
from supabase import create_client, Client

try:
    with open('.env') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, value = line.split('=', 1)
            os.environ[key] = value.strip(' "\'')
except FileNotFoundError:
    pass

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Check Grits (Team ID 4)
print("Checking Grits Player Data...")
# Check confirmed players #29 Yujiro Isobe, #86 Junseo Park
response = supabase.table('alih_players').select('*').eq('team_id', 4).in_('jersey_number', [29, 86, 61]).execute()

for p in response.data:
    print(f"Player #{p.get('jersey_number')} (ID: {p.get('id')})")
    print(f"  Name (EN): {p.get('name_en')}")
    print(f"  Name (JA): {p.get('name_ja')}")
    print(f"  Photo:     {p.get('photo_url')}")
    print(f"  Instagram: {p.get('instagram_url')}")
    print("-" * 20)
