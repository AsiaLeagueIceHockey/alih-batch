import os
import requests
import time
from bs4 import BeautifulSoup
from supabase import create_client, Client

# 1. Supabase Setup
# Load .env manually to be dependency-free
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
TARGET_URL = "https://asiaicehockey.com/team/hlanyang/player"
TEAM_ID = 1  # HL Anyang
BUCKET_NAME = "player-images"

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


def parse_int(text):
    try:
        return int(text.strip())
    except ValueError:
        return None

def upload_image_to_storage(image_url, filename):
    """
    Downloads image from URL and uploads to Supabase Storage.
    Returns the public URL of the uploaded image.
    """
    try:
        # Download image
        print(f"  - Downloading image: {image_url}")
        img_response = requests.get(image_url)
        if img_response.status_code != 200:
            print(f"  - Failed to download image. Status: {img_response.status_code}")
            return None
        
        image_bytes = img_response.content
        content_type = img_response.headers.get('Content-Type', 'image/jpeg')

        # Upload to Supabase Storage
        # path: hl_anyang/{filename}
        storage_path = f"hl_anyang/{filename}"
        
        print(f"  - Uploading to Storage: {BUCKET_NAME}/{storage_path}")
        
        # Check if file exists (optional, or just overwrite)
        # We will use upsert normally, but the python client might need specific handle
        # update() or upload(..., file_options={"upsert": "true"})
        
        res = supabase.storage.from_(BUCKET_NAME).upload(
            file=image_bytes,
            path=storage_path,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        
        # Get Public URL
        # The return of upload might not contain public URL directly depending on version, 
        # but we can construct it or ask for it.
        public_url_res = supabase.storage.from_(BUCKET_NAME).get_public_url(storage_path)
        return public_url_res

    except Exception as e:
        print(f"  - Error uploading image: {e}")
        return None

def scrape_hl_anyang_images():
    ensure_bucket_exists()
    print(f"Fetching {TARGET_URL}...")
    try:
        response = requests.get(TARGET_URL)
        # The site might be UTF-8 or Shift_JIS, usually UTF-8 for modern sites but previous script used shift_jis. 
        # However, asiaicehockey.com seems modern. Let's try auto or UTF-8. 
        # Inspecting previous output, it looked like standard UTF-8 or similar.
        # response.encoding = 'utf-8' # Default
    except Exception as e:
        print(f"Failed to fetch URL: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')

    # Find all player cards
    cards = soup.select('.uk-card')
    print(f"Found {len(cards)} cards (some might be non-player cards).")

    updated_count = 0

    for card in cards:
        try:
            # 1. Jersey Number (e.g., "32")
            # Structure: <p class="uk-text-large">32</p>
            jersey_elem = card.select_one('.uk-text-large')
            if not jersey_elem:
                continue # Not a player card probably
            
            jersey_number_str = jersey_elem.text.strip()
            jersey_number = parse_int(jersey_number_str)
            
            if jersey_number is None:
                continue

            # 2. Names
            # Japanese: <h3 class="uk-card-title ...">イ・ヨンスン</h3>
            # English: <p class="uk-text-meta ...">YEONSEUNG LEE</p>
            name_ja_elem = card.select_one('.uk-card-title')
            name_en_elem = card.select_one('.uk-text-meta')
            
            name_ja = name_ja_elem.text.strip() if name_ja_elem else None
            name_en = name_en_elem.text.strip() if name_en_elem else None

            # 3. Photo URL
            # <img ... data-src="...">
            img_elem = card.select_one('img')
            photo_source_url = None
            if img_elem:
                if 'data-src' in img_elem.attrs:
                    photo_source_url = img_elem['data-src']
                elif 'src' in img_elem.attrs:
                    photo_source_url = img_elem['src']
            
            if not photo_source_url:
                print(f"Skipping Player {jersey_number} (No Image)")
                continue

            print(f"Processing Player #{jersey_number}: {name_en} ({name_ja})")
            
            # 4. Upload Image
            # Filename: jersey_name_en.jpg (sanitize name)
            safe_name = "".join(c for c in name_en if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_').lower()
            filename = f"{jersey_number}_{safe_name}.jpg"
            
            public_photo_url = upload_image_to_storage(photo_source_url, filename)
            
            if not public_photo_url:
                print(f"  - Failed to get public URL for #{jersey_number}")
                continue

            print(f"  - Public URL: {public_photo_url}")

            # 5. Update Database
            # 5. Update Database
            update_data = {
                "photo_url": public_photo_url,
                "name_en": name_en,
                "name_ja": name_ja,
                "updated_at": "now()"
            }

            # STRATEGY CHANGED: 'upsert' failed because no unique index on (team_id, jersey_number).
            # New Strategy: SELECT id FROM alih_players WHERE team_id=... AND jersey_number=...
            # If exists -> UPDATE. If not -> INSERT.

            existing_res = supabase.table('alih_players').select('id').eq('team_id', TEAM_ID).eq('jersey_number', jersey_number).execute()
            
            if existing_res.data and len(existing_res.data) > 0:
                # Update existing
                player_id = existing_res.data[0]['id']
                print(f"  - Updating existing player (ID: {player_id})")
                supabase.table('alih_players').update(update_data).eq('id', player_id).execute()
            else:
                # Insert new
                print(f"  - Inserting new player")
                full_data = {
                    "team_id": TEAM_ID,
                    "jersey_number": jersey_number,
                    **update_data
                }
                supabase.table('alih_players').insert(full_data).execute()
            
            updated_count += 1
            print(f"  - Database updated.")

        except Exception as e:
            print(f"Error processing card: {e}")
            continue

    print(f"Finished. Updated {updated_count} players.")

if __name__ == "__main__":
    scrape_hl_anyang_images()
