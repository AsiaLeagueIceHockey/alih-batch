import os
import requests
import time
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from supabase import create_client, Client

# 1. Supabase Setup
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

if not SUPABASE_URL or not SUPABASE_KEY:
    raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Constants
LIST_URL = "https://www.icebucks.jp/players/"
TEAM_ID = 5  # Nikko Ice Bucks
BUCKET_NAME = "player-images"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

def parse_int(text):
    try:
        if not text: return None
        # Remove non-digits
        digits = re.sub(r'\D', '', text)
        return int(digits) if digits else None
    except ValueError:
        return None

def ensure_bucket_exists():
    try:
        buckets = supabase.storage.list_buckets()
        bucket_names = [b.name for b in buckets]
        if BUCKET_NAME not in bucket_names:
            print(f"Creating bucket '{BUCKET_NAME}'...")
            supabase.storage.create_bucket(BUCKET_NAME, options={'public': True})
    except Exception as e:
        print(f"Warning: Bucket check failed: {e}")

def upload_image_to_storage(image_url, filename):
    try:
        print(f"  - Downloading image: {image_url}")
        img_response = requests.get(image_url, headers=HEADERS)
        if img_response.status_code != 200:
            print(f"  - Failed to download image. Status: {img_response.status_code}")
            return None
        
        image_bytes = img_response.content
        content_type = img_response.headers.get('Content-Type', 'image/jpeg')

        storage_path = f"icebucks/{filename}"
        
        res = supabase.storage.from_(BUCKET_NAME).upload(
            file=image_bytes,
            path=storage_path,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        
        public_url_res = supabase.storage.from_(BUCKET_NAME).get_public_url(storage_path)
        return public_url_res

    except Exception as e:
        print(f"  - Error uploading image: {e}")
        return None

def scrape_icebucks():
    ensure_bucket_exists()
    print(f"Fetching List: {LIST_URL}...")
    try:
        response = requests.get(LIST_URL, headers=HEADERS)
    except Exception as e:
        print(f"Failed to fetch URL: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Structure: ul.member-list > li
    # Iterate all ul.member-list
    member_lists = soup.find_all('ul', class_='member-list')
    print(f"Found {len(member_lists)} member lists.")
    
    updated_count = 0
    
    for ul in member_lists:
        items = ul.find_all('li')
        for li in items:
            try:
                # 1. Jersey
                # <div class="u-number"><span>33</span></div>
                num_div = li.select_one('.u-number span')
                if not num_div: continue
                
                jersey_number = parse_int(num_div.text)
                if jersey_number is None: continue
                
                # 2. Names
                # <h3 class="player-name"><span class="ja">...</span><span class="en">...</span></h3>
                name_ja_elem = li.select_one('.player-name .ja')
                name_en_elem = li.select_one('.player-name .en')
                
                name_ja = name_ja_elem.text.strip() if name_ja_elem else None
                name_en = name_en_elem.text.strip() if name_en_elem else None
                
                print(f"Processing #{jersey_number}: {name_en} ({name_ja})")
                
                # 3. Instagram
                # <li class="Instagram-icon"><a href="...">...</a></li>
                # Need to be careful not to get team insta if it happens to be somehow nested (unlikely based on check)
                instagram_url = None
                insta_a = li.select_one('.Instagram-icon a')
                if insta_a:
                     href = insta_a.get('href')
                     if href and 'instagram.com' in href:
                         instagram_url = href
                         print(f"  - Instagram: {instagram_url}")

                # 4. Image
                # <figure class="zoom"><img src="..."></figure>
                img_tag = li.select_one('figure.zoom img')
                photo_source_url = None
                if img_tag:
                     photo_source_url = img_tag.get('src')
                
                # 5. Upload Image
                public_photo_url = None
                if photo_source_url:
                    safe_name = "".join(c for c in (name_en or "player") if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_').lower()
                    if not safe_name: safe_name = f"player_{jersey_number}"
                    filename = f"{jersey_number}_{safe_name}.jpg"
                    
                    public_photo_url = upload_image_to_storage(photo_source_url, filename)
                    if public_photo_url:
                        print(f"  - Public URL: {public_photo_url}")

                # 6. DB Update
                update_data = {
                    "name_ja": name_ja,
                    "updated_at": "now()"
                }
                if name_en:
                    update_data["name_en"] = name_en
                if public_photo_url:
                    update_data["photo_url"] = public_photo_url
                if instagram_url:
                    update_data["instagram_url"] = instagram_url

                # Upsert
                existing_res = supabase.table('alih_players').select('id').eq('team_id', TEAM_ID).eq('jersey_number', jersey_number).execute()
                
                if existing_res.data and len(existing_res.data) > 0:
                    player_id = existing_res.data[0]['id']
                    supabase.table('alih_players').update(update_data).eq('id', player_id).execute()
                    print(f"  - Database updated (ID: {player_id})")
                else:
                    print(f"  - Inserting new player")
                    full_data = {
                        "team_id": TEAM_ID,
                        "jersey_number": jersey_number,
                        **update_data
                    }
                    supabase.table('alih_players').insert(full_data).execute()
                    print(f"  - Database inserted")
                
                updated_count += 1
                time.sleep(0.5)

            except Exception as e:
                print(f"Error processing item: {e}")
                continue

    print(f"Finished. Updated {updated_count} players.")

if __name__ == "__main__":
    scrape_icebucks()
