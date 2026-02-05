import os
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client
import urllib.parse
import time

# --- Configuration ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
BUCKET = "images"
TEAM_ID = 6  # Stars Kobe
BASE_URL = "https://stars-kobe.com"

# Hardcoded verification from Browser Subagent
JERSEY_MAP = {
    "ISHIDA": 32,
    "ONODERA": 10,
    "JANG-G": 35,
    "ZAIKE": 9,
    "CHO": 23,
    "AOYAMA": 54,
    "LEE": 61,
    "WATANABE": 65,
    "KIM": 56,
    "YOO": 81,
    "ODERMATTｰM": 10,
    "ODERMATTｰT": 13,
    "YANO-RIN": 14,
    "YANO-RYO": 19,
    "AYRE": 22,
    "NEGISHI": 29,
    "HOU": 77,
    "JANG-H": 78,
    "PARK": 85,
    "KAWAGISHI": 86,
    "WANG": 91,
    "SHIN": 92
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing Supabase credentials in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def ensure_bucket_exists():
    """Ensure the storage bucket exists."""
    try:
        buckets = supabase.storage.list_buckets()
        bucket_names = [b.name for b in buckets]
        if BUCKET not in bucket_names:
            print(f"Creating bucket '{BUCKET}'...")
            supabase.storage.create_bucket(BUCKET, options={"public": True})
        else:
            print(f"Bucket '{BUCKET}' exists.")
    except Exception as e:
        print(f"Error checking/creating bucket: {e}")

def upload_image_from_url(url, slug):
    """Downloads image and uploads to Supabase Storage."""
    if not url:
        return None
    
    try:
        # Determine extension? The sample was .webp
        ext = "jpg"
        if ".webp" in url:
            ext = "webp"
        elif ".png" in url:
            ext = "png"
            
        filename = f"stars/{slug}.{ext}"
        
        print(f"  - Downloading image: {url}")
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        image_data = resp.content
        
        print(f"  - Uploading to {filename}...")
        supabase.storage.from_(BUCKET).upload(
            path=filename,
            file=image_data,
            file_options={"content-type": f"image/{ext}", "upsert": "true"}
        )
        
        public_url = supabase.storage.from_(BUCKET).get_public_url(filename)
        return public_url
    except Exception as e:
        print(f"  ! Error uploading image: {e}")
        return None

def main():
    ensure_bucket_exists()
    
    processed_count = 0
    total = len(JERSEY_MAP)
    print(f"Starting processing for {total} players...")
    
    for slug, jersey_number in JERSEY_MAP.items():
        # Encode slug for URL if needed (requests handles basics but let's be safe for visual logs)
        # requests will encode 'ODERMATTｰT' correctly.
        player_url = f"{BASE_URL}/{slug}" 
        
        print(f"\nProcessing {slug} (Jersey: {jersey_number})...")
        print(f"  - Fetching {player_url}")
        
        try:
            p_resp = requests.get(player_url, headers=HEADERS, timeout=10)
            p_resp.raise_for_status()
            p_soup = BeautifulSoup(p_resp.text, 'html.parser')
            
            # Extract Name from Title
            # <title>STARS KOBE | ISHIDA</title>
            page_title = p_soup.title.string if p_soup.title else ""
            if not page_title: 
                print("  ! Title not found")
                
            name = page_title.replace('STARS KOBE |', '').strip()
            print(f"  - Name: {name}")
            
            # Extract Image
            # Subagent identified "section img" as robust
            img_tag = p_soup.select_one('section img')
            photo_url = None
            if img_tag:
                # Sometimes src is lazy loaded or dynamic?
                # Check for src, data-src, etc.
                if img_tag.get('src'):
                    photo_url = img_tag['src']
                elif img_tag.get('data-src'):
                    photo_url = img_tag['data-src']
            
            if not photo_url:
                print("  ! No image found in 'section img', trying 'img'")
                # Fallback: Find largest image? No, assume section img correct from subagent.
                # If failed, maybe layout changed?
                pass
            
            # Clean slug (remove unicode for filename safety optionally? No, Supabase supports it)
            # Actually, standardizing filename to ASCII might be safer but slug is unique ID.
            # I'll keep it as is.
            storage_url = upload_image_from_url(photo_url, slug)
            
            # Upsert DB
            data = {
                "team_id": TEAM_ID,
                "jersey_number": jersey_number,
                "name_en": name,
                "name_ko": name,
                "photo_url": storage_url
            }
            
            if storage_url:
                print(f"  - Upserting DB: {name} (#{jersey_number})")
                supabase.table("alih_players").upsert(data, on_conflict="team_id, jersey_number").execute()
                processed_count += 1
            else:
                print("  ! Skipping upsert due to missing photo")
            
            time.sleep(1) # Be polite
            
        except Exception as e:
            print(f"  ! Error processing {slug}: {e}")
            
    print(f"\nDone. Processed {processed_count}/{total} players.")

if __name__ == "__main__":
    main()
