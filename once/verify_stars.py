import os
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TEAM_ID = 6

if not SUPABASE_URL or not SUPABASE_KEY:
    # Try loading from .env manually if env vars missing
    try:
        with open('.env') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    os.environ[k] = v.strip('"\'')
        SUPABASE_URL = os.environ.get("SUPABASE_URL")
        SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
    except:
        pass

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print(f"Verifying Team ID {TEAM_ID} (Stars Kobe)...")

# Count
res = supabase.table('alih_players').select('*', count='exact').eq('team_id', TEAM_ID).execute()
print(f"Total Players: {res.count} (Expected 22)")

# Check specifically for mapped players
# Check Odermatt brothers
print("\nChecking Specific Players:")
odermatts = supabase.table('alih_players').select('name, jersey_number, photo_url').eq('team_id', TEAM_ID).ilike('name', '%ODERMATT%').execute()
for p in odermatts.data:
    print(f" - #{p['jersey_number']} {p['name']} (Photo: {'OK' if p['photo_url'] else 'MISSING'})")

# Check Total Photo Coverage
missing_photos = [p for p in res.data if not p.get('photo_url')]
if missing_photos:
    print(f"\n!! MISSING PHOTOS: {len(missing_photos)} players")
    for p in missing_photos:
        print(f" - #{p['jersey_number']} {p['name']}")
else:
    print("\nAll players have photos! ✅")
