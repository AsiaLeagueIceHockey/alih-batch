import os
import requests
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
BUCKET = "images"
HEADERS = {"User-Agent": "Mozilla/5.0"}

if not SUPABASE_URL or not SUPABASE_KEY:
    try:
        with open('.env') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    os.environ[k] = v.strip('"\'')
        SUPABASE_URL = os.environ.get("SUPABASE_URL")
        SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
    except: pass

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def fix_yoo():
    # URL from stars_photos_batch1.json
    url = "https://storage.googleapis.com/studio-design-asset-files/projects/XKOkgY6O4/s-4000x4000_v-frms_webp_ba3085d7-0dc6-453e-8d6f-87700ff5d149_small.webp"
    slug = "YOO"
    jersey = 81
    
    print(f"Testing URL for {slug}: {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        print(f"Status: {resp.status_code}")
        if resp.status_code != 200:
            print("URL is invalid or 404.")
        else:
            print(f"Downloaded {len(resp.content)} bytes.")
            filename = f"stars/{slug}.webp"
            print(f"Uploading to {filename}...")
            supabase.storage.from_(BUCKET).upload(
                path=filename,
                file=resp.content,
                file_options={"content-type": "image/webp", "upsert": "true"}
            )
            public_url = supabase.storage.from_(BUCKET).get_public_url(filename)
            print(f"Public URL: {public_url}")
            
            print("Updating DB...")
            res = supabase.table('alih_players').update({'photo_url': public_url}).eq('team_id', 6).eq('jersey_number', jersey).execute()
            print(f"Update result: {res.data}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_yoo()
