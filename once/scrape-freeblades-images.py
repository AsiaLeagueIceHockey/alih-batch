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
LIST_URL = "https://freeblades.jp/player/"
TEAM_ID = 3  # Tohoku Free Blades
BUCKET_NAME = "player-images"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

def parse_int(text):
    try:
        if not text: return None
        return int(text.strip())
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

        storage_path = f"freeblades/{filename}"
        
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
        
        # Look for instagram.com link in li.instagram class
        # Priority 1: li.instagram > a
        insta_li = soup.select_one('li.instagram')
        if insta_li:
            a = insta_li.find('a')
            if a and 'instagram.com' in a.get('href', ''):
                return a['href']
        
        # Priority 2: Any instagram link that is NOT the team's official one
        # Team often uses: https://www.instagram.com/freeblades/
        all_insta = soup.find_all(lambda tag: tag.name == 'a' and 'instagram.com' in str(tag.get('href')))
        for a in all_insta:
            href = a['href']
            if 'freeblades' not in href and 'instagram.com' in href:
                 return href
        
        return None
    except Exception as e:
        print(f"  - Error fetching detail: {e}")
        return None

def scrape_freeblades():
    ensure_bucket_exists()
    print(f"Fetching List: {LIST_URL}...")
    try:
        response = requests.get(LIST_URL, headers=HEADERS)
    except Exception as e:
        print(f"Failed to fetch URL: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')

    # Strategy: Find all player containers.
    # From checks: <div class="player-title"> is inside the anchor inside the wrapper.
    # It seems the wrapper is an <a> tag directly if looking at the card structure.
    # "<a href=... ><div ... class="player-number">...</div>...</a>"
    
    # Let's find all elements that look like player cards.
    # A reliable way based on check script:
    # <a> containing <div class="player-number">
    
    cards = []
    candidates = soup.find_all('a', href=True)
    for c in candidates:
        if c.select_one('.player-number'):
            cards.append(c)
            
    print(f"Found {len(cards)} player cards.")
    
    updated_count = 0
    
    for card in cards:
        try:
            detail_url = card['href']
            
            # Jersey
            # <div class="player-number"><div class="before_">33</div></div>
            num_div = card.select_one('.player-number .before_')
            if not num_div:
                continue
            
            jersey_number = parse_int(num_div.text)
            if jersey_number is None:
                continue

            # Names
            # <div class="player-title">伊藤 崇之<span class="name-en">ITO, Takayuki</span></div>
            title_div = card.select_one('.player-title')
            name_en_span = title_div.select_one('.name-en')
            
            name_en = name_en_span.text.strip() if name_en_span else None
            
            # Remove en span to get JA name
            if name_en_span:
                name_en_span.extract()
            name_ja = title_div.text.strip() if title_div else None
            
            # Image
            # <img class="player-image1 ... data-src="...">
            img_elem = card.select_one('img.player-image1')
            photo_source_url = None
            if img_elem:
                if img_elem.get('data-src'):
                    photo_source_url = img_elem['data-src']
                elif img_elem.get('src'):
                    photo_source_url = img_elem['src']

            print(f"Processing #{jersey_number}: {name_en} ({name_ja})")
            
            # Get Instagram from detail page
            instagram_url = get_instagram_from_detail(detail_url)
            if instagram_url:
                print(f"  - Instagram: {instagram_url}")
            
            # Upload Image
            public_photo_url = None
            if photo_source_url:
                safe_name = "".join(c for c in (name_en or "player") if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_').lower()
                filename = f"{jersey_number}_{safe_name}.jpg"
                public_photo_url = upload_image_to_storage(photo_source_url, filename)
                if public_photo_url:
                     print(f"  - Public URL: {public_photo_url}")
            
            # DB Update
            update_data = {
                "name_ja": name_ja,
                "updated_at": "now()"
            }
            if name_en:
                 # Normalize EN name "ITO, Takayuki" -> "Takayuki ITO" ?? Or keep "ITO, Takayuki"?
                 # User Request format in Phase 1 was "Matt DALTON" (First Last).
                 # Site gives "ITO, Takayuki" (Last, First).
                 # Ideally we format it to First Last if possible, or just keep as is.
                 # Let's keep as is for now or simple swap if comma exists.
                 if ',' in name_en:
                     parts = name_en.split(',')
                     if len(parts) == 2:
                         update_data["name_en"] = f"{parts[1].strip()} {parts[0].strip()}"
                     else:
                         update_data["name_en"] = name_en
                 else:
                     update_data["name_en"] = name_en

            if public_photo_url:
                update_data["photo_url"] = public_photo_url
            if instagram_url:
                update_data["instagram_url"] = instagram_url

            # Upsert Logic
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
            # Be nice to the server
            time.sleep(0.5)

        except Exception as e:
            print(f"Error processing card: {e}")
            continue

    print(f"Finished. Updated {updated_count} players.")

if __name__ == "__main__":
    scrape_freeblades()
