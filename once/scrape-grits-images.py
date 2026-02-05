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
LIST_URL = "https://grits-sport.com/players"
TEAM_ID = 4  # Yokohama Grits
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

        storage_path = f"grits/{filename}"
        
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

def get_instagram_from_detail(detail_url):
    try:
        print(f"  - Fetching detail: {detail_url}")
        response = requests.get(detail_url, headers=HEADERS)
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for instagram links
        all_insta = soup.find_all(lambda tag: tag.name == 'a' and 'instagram.com' in str(tag.get('href')))
        
        for a in all_insta:
            href = a['href']
            # Exclude team account and non-player accounts if obvious
            if 'yokohama_grits' not in href and 'instagram.com' in href:
                 return href
        
        return None
    except Exception as e:
        print(f"  - Error fetching detail: {e}")
        return None

def scrape_grits():
    ensure_bucket_exists()
    print(f"Fetching List: {LIST_URL}...")
    try:
        response = requests.get(LIST_URL, headers=HEADERS)
    except Exception as e:
        print(f"Failed to fetch URL: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Structure: figure.wp-block-image > a (Link+Img) + figcaption (Text)
    figures = soup.select('figure.wp-block-image')
    print(f"Found {len(figures)} figure elements.")
    
    updated_count = 0
    
    for fig in figures:
        try:
            # 1. Detail URL & Image
            a_tag = fig.find('a')
            if not a_tag: continue
            
            detail_url = a_tag.get('href')
            if not detail_url or '/player/' not in detail_url:
                continue # Skip if not a player link
                
            img_tag = a_tag.find('img')
            photo_source_url = img_tag.get('src') if img_tag else None
            
            # 2. Jersey & Name
            figcaption = fig.find('figcaption')
            if not figcaption: continue
            
            # Jersey is usually in <mark> inside figcaption
            mark = figcaption.find('mark')
            jersey_number = None
            if mark:
                jersey_number = parse_int(mark.get_text())
                # Remove mark text from full text to get name
                mark.extract() # Modifies soup tree, but that's fine for this loop
            
            if jersey_number is None:
                # Try finding digits in the caption text if mark missing?
                # But visual inspection showed mark. Skip if no number.
                print(f"Skipping (No Jersey Number): {figcaption.get_text().strip()[:20]}")
                continue
                
            # Names: "磯部 裕次郎/ YUJIRO  ISOBE"
            full_text = figcaption.get_text().strip()
            
            name_ja = None
            name_en = None
            
            if '/' in full_text:
                parts = full_text.split('/', 1)
                name_ja = parts[0].strip()
                name_en = parts[1].strip()
            else:
                # Fallback
                name_ja = full_text
            
            print(f"Processing #{jersey_number}: {name_en} ({name_ja})")
            
            # 3. Instagram
            instagram_url = get_instagram_from_detail(detail_url)
            if instagram_url:
                print(f"  - Instagram: {instagram_url}")
            
            # 4. Upload Image
            public_photo_url = None
            if photo_source_url:
                # Use jersey + en name for filename
                safe_name = "".join(c for c in (name_en or "player") if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_').lower()
                if not safe_name: safe_name = f"player_{jersey_number}"
                filename = f"{jersey_number}_{safe_name}.jpg"
                
                public_photo_url = upload_image_to_storage(photo_source_url, filename)
                if public_photo_url:
                     print(f"  - Public URL: {public_photo_url}")

            # 5. DB Update
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
    scrape_grits()
