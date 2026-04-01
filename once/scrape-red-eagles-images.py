import os
import requests
import time
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
TARGET_URL = "https://redeagles.co.jp/team/player/"
TEAM_ID = 2  # Red Eagles Hokkaido
BUCKET_NAME = "player-images"

def parse_int(text):
    try:
        return int(text.strip())
    except ValueError:
        return None

def ensure_bucket_exists():
    """Create bucket if it doesn't exist"""
    try:
        buckets = supabase.storage.list_buckets()
        bucket_names = [b.name for b in buckets]
        if BUCKET_NAME not in bucket_names:
            print(f"Creating bucket '{BUCKET_NAME}'...")
            supabase.storage.create_bucket(BUCKET_NAME, options={'public': True})
            print(f"Bucket '{BUCKET_NAME}' created.")
        else:
            print(f"Bucket '{BUCKET_NAME}' exists.")
    except Exception as e:
        print(f"Warning: Could not check/create bucket: {e}")

def upload_image_to_storage(image_url, filename):
    try:
        # Download image
        print(f"  - Downloading image: {image_url}")
        # Need user-agent for some sites
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
        img_response = requests.get(image_url, headers=headers)
        if img_response.status_code != 200:
            print(f"  - Failed to download image. Status: {img_response.status_code}")
            return None
        
        image_bytes = img_response.content
        content_type = img_response.headers.get('Content-Type', 'image/jpeg')

        # Upload to Supabase Storage
        # path: red_eagles/{filename}
        storage_path = f"red_eagles/{filename}"
        
        # print(f"  - Uploading to Storage: {BUCKET_NAME}/{storage_path}")
        
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

def scrape_red_eagles_images():
    ensure_bucket_exists()
    print(f"Fetching {TARGET_URL}...")
    try:
        response = requests.get(TARGET_URL)
        response.encoding = 'utf-8' # Ensure utf-8
    except Exception as e:
        print(f"Failed to fetch URL: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')

    # Find sections first to be safe, then li
    # Or just select all 'li' inside sections that have players
    # Based on analysis: content area > section > ul > li
    
    # We found sections: GK, DF, FW, etc.
    sections = soup.find_all('section')
    print(f"Found {len(sections)} sections.")
    
    updated_count = 0
    
    for section in sections:
        # Check if this section implies players (skip Supporter, Staff if needed, but Staff might be useful later? Stick to players)
        # Players are in GK, DF, FW sections.
        # Staff is in "TEAM STAFF". Supporter "SUPPORTER".
        h2 = section.find('h2')
        header_text = h2.text.strip() if h2 else ""
        
        if header_text in ["TEAM STAFF", "SUPPORTER"]:
            print(f"Skipping section: {header_text}")
            continue
            
        print(f"Processing section: {header_text}")
        
        items = section.select('ul > li')
        for li in items:
            try:
                # 1. Jersey Number <div class="u_num">
                num_div = li.select_one('.u_num')
                if not num_div:
                    continue # Not a player card
                
                jersey_number = parse_int(num_div.text)
                if jersey_number is None:
                    continue
                
                # 2. Names
                # Japanese: dd > div > p (first one)
                # English: dd > div > p.f_en
                dd = li.select_one('dd')
                if not dd:
                    continue
                
                info_div = dd.select_one('div') # First div inside dd
                name_ja_elem = info_div.find('p') if info_div else None # First p
                name_en_elem = info_div.select_one('.f_en') if info_div else None
                
                name_ja = name_ja_elem.text.strip() if name_ja_elem else None
                name_en = name_en_elem.text.strip() if name_en_elem else None
                
                # 3. Instagram
                # dd > div.sns > a[href*="instagram.com"]
                sns_div = dd.select_one('.sns')
                instagram_url = None
                if sns_div:
                    insta_link = sns_div.find(lambda tag: tag.name == 'a' and 'instagram.com' in str(tag.get('href')))
                    if insta_link:
                        instagram_url = insta_link['href']
                
                # 4. Photo
                # dt > a > img OR dt > img
                dt = li.select_one('dt')
                img_elem = dt.find('img') if dt else None
                photo_source_url = None
                
                if img_elem:
                    src = img_elem.get('src')
                    if src:
                        # Resolve relative URL "../images/..." to absolute
                        photo_source_url = urljoin(TARGET_URL, src)
                
                print(f"Processing #{jersey_number}: {name_en} ({name_ja})")
                
                # Upload Image if exists
                public_photo_url = None
                if photo_source_url:
                    safe_name = "".join(c for c in (name_en or "player") if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_').lower()
                    filename = f"{jersey_number}_{safe_name}.jpg"
                    public_photo_url = upload_image_to_storage(photo_source_url, filename)
                    if public_photo_url:
                         print(f"  - Public URL: {public_photo_url}")
                else:
                    print("  - No photo found")

                # Update Database
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
                    print(f"  - Instagram: {instagram_url}")

                # Strategy: SELECT id -> UPDATE or INSERT
                existing_res = supabase.table('alih_players').select('id').eq('team_id', TEAM_ID).eq('jersey_number', jersey_number).execute()
                
                if existing_res.data and len(existing_res.data) > 0:
                    player_id = existing_res.data[0]['id']
                    # print(f"  - Updating existing player (ID: {player_id})")
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
                
            except Exception as e:
                print(f"Error processing item: {e}")
                continue

    print(f"Finished. Updated {updated_count} players.")

if __name__ == "__main__":
    scrape_red_eagles_images()
