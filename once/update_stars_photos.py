import os
import requests
from supabase import create_client, Client
import json
import time

# --- Configuration ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
BUCKET = "images"
TEAM_ID = 6  # Stars Kobe
BASE_URL = "https://stars-kobe.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing Supabase credentials in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def upload_image(url, slug):
    if not url: return None
    try:
        ext = "webp" if ".webp" in url else "jpg"
        filename = f"stars/{slug}.{ext}"
        print(f"  - Downloading from {url[:30]}...")
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        
        print(f"  - Uploading to {filename}...")
        supabase.storage.from_(BUCKET).upload(
            path=filename,
            file=resp.content,
            file_options={"content-type": f"image/{ext}", "upsert": "true"}
        )
        return supabase.storage.from_(BUCKET).get_public_url(filename)
    except Exception as e:
        print(f"  ! Error uploading: {e}")
        return None

def main():
    if not os.path.exists('stars_photos_final.json'):
        print("Error: stars_photos_final.json not found.")
        return

    with open('stars_photos_final.json', 'r') as fp:
        players = json.load(fp)
                
    print(f"Loaded {len(players)} players from stars_photos_final.json")
    
    processed = 0
    for p in players:
        slug = p['slug']
        photo_url = p['photo']
        jersey = p.get('jersey_number')
        
        if not jersey:
            print(f"Skipping {slug}: No Jersey Number in JSON")
            continue
        
        print(f"\nProcessing {slug} (#{jersey})...")
        
        # 1. Upload Photo
        storage_url = upload_image(photo_url, slug)
        
        if storage_url:
            # 2. Update DB by Jersey Number
            # We only UPDATE photo_url. We assume Name/Etc is correct in DB now.
            # But the user might want name updated? User said "update photo".
            # I'll update photo_url only to be safe?
            # Or fetch name again? 
            # "jersey_num을 기반으로 조회해서 photo를 업로드하고 해당 url을 photo_url 넣어주도록"
            # It implies updating ONLY photo_url is the main goal, but previously Name was scraped.
            # I will Update Photo URL.
            
            data = {"photo_url": storage_url}
            
            # Check for existing record
            existing_res = supabase.table('alih_players').select('id, name').eq('team_id', TEAM_ID).eq('jersey_number', jersey).execute()
            
            if existing_res.data and len(existing_res.data) > 0:
                player_id = existing_res.data[0]['id']
                current_name = existing_res.data[0]['name']
                print(f"  - Found Player: {current_name} (ID: {player_id})")
                print(f"  - Updating photo_url...")
                supabase.table('alih_players').update(data).eq('id', player_id).execute()
                processed += 1
            else:
                print(f"  ! SKIPPING: #{jersey} {slug} (No matching record found in DB)")
        
        time.sleep(0.5)
        
    print(f"\nDone. Updated {processed} players.")

if __name__ == "__main__":
    main()
