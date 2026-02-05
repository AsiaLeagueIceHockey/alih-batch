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

# Check Player #31, #32, #97 for HL Anyang (Team ID 1)
print("Checking Player Data...")
response = supabase.table('alih_players').select('*').eq('team_id', 1).in_('jersey_number', [31, 32, 97]).execute()

for p in response.data:
    print(f"Player #{p.get('jersey_number')} (ID: {p.get('id')}) - {p.get('name')}")
    print(f"  photo_url: {p.get('photo_url')}")
    print(f"  name_en:   {p.get('name_en')}")
    print(f"  name_ja:   {p.get('name_ja')}")
    print(f"  name_ja:   {p.get('name_ja')}")
    print("-" * 20)

print("\nRunning Test Update on ID 74088...")
try:
    test_res = supabase.table('alih_players').update({'name_en': 'TEST_UPDATE'}).eq('id', 74088).execute()
    print(f"Update Result Data: {test_res.data}")
    if not test_res.data:
        print("!! WARNING: Update returned empty data. This implies 0 rows updated (likely RLS).")
    else:
        print("Update successful (returned data).")
except Exception as e:
    print(f"Update Failed: {e}")
