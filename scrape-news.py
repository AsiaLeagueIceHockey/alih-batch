import os
import feedparser
import datetime
from supabase import create_client, Client

# ... (RSS_FEEDS 리스트는 동일) ...

# --- 1. Supabase 클라이언트 초기화 ---
def init_supabase():
    """GitHub Actions Secrets에서 URL과 키를 가져와 Supabase 클라이언트를 초기화합니다."""
    url = os.environ.get("SUPABASE_URL")
    
    # [수정됨] 환경 변수 이름을 'SUPABASE_SERVICE_KEY'로 변경
    key = os.environ.get("SUPABASE_SERVICE_KEY") 
    
    if not url or not key:
        # [수정됨] 에러 메시지도 일치시킴
        print("Error: SUPABASE_URL or SUPABASE_SERVICE_KEY is not set.") 
        exit(1)
        
    return create_client(url, key)

# --- 2. get_latest_publish_time 함수 (이전과 동일) ---
def get_latest_publish_time(supabase: Client) -> datetime.datetime:
    # ... (이전 코드와 동일) ...
    try:
        response = supabase.table('alih_news') \
                           .select('published_at') \
                           .order('published_at', desc=True) \
                           .limit(1) \
                           .execute()
        
        if response.data:
            latest_time_str = response.data[0]['published_at']
            return datetime.datetime.fromisoformat(latest_time_str)
        else:
            print("No existing data found. Setting baseline date to 2025-08-15.")
            return datetime.datetime.fromisoformat('2025-08-15T00:00:00+00:00')
            
    except Exception as e:
        print(f"Error fetching latest publish time: {e}")
        return datetime.datetime.fromisoformat('2025-08-15T00:00:00+00:00')

# --- 3. main 함수 (이전과 동일) ---
def main():
    supabase = init_supabase()
    
    latest_time = get_latest_publish_time(supabase)
    print(f"Fetching news published after: {latest_time}")

    articles_to_insert = []
    
    for feed in RSS_FEEDS:
        print(f"Parsing feed for language: {feed['language']}...")
        parsed_feed = feedparser.parse(feed['url'])
        
        for entry in parsed_feed.entries:
            try:
                entry_time_dt = datetime.datetime(*entry.published_parsed[:6], 
                                                tzinfo=datetime.timezone.utc)
                
                if entry_time_dt > latest_time:
                    created_at_dt = datetime.datetime.now(datetime.timezone.utc)
                    
                    row = {
                        'title': entry.title,
                        'summary': entry.summary,
                        'origin_url': entry.link,
                        'language': feed['language'], 
                        'published_at': entry_time_dt.isoformat(), 
                        'created_at': created_at_dt.isoformat()   
                    }
                    articles_to_insert.append(row)
                    
            except Exception as e:
                print(f"Error processing entry {entry.link}: {e}")

    if articles_to_insert:
        print(f"Found {len(articles_to_insert)} new articles. Inserting to Supabase...")
        try:
            response = supabase.table('alih_news').upsert(
                articles_to_insert,
                on_conflict='origin_url',  
                ignore_duplicates=True  
            ).execute()
            
            print(f"Insert response: {response.data}")
            print(f"Successfully inserted/ignored {len(response.data)} articles.")
            
        except Exception as e:
            print(f"Error inserting data to Supabase: {e}")
    else:
        print("No new articles found.")

if __name__ == "__main__":
    main()