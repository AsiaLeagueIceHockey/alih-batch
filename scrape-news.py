import os
import feedparser
import datetime
from supabase import create_client, Client
from deep_translator import GoogleTranslator

# --- 0. RSS 피드 목록 ---
# 사용자가 확정한 리스트
RSS_FEEDS = [
    {'url': 'https://news.google.com/rss/search?q=HL%EC%95%88%EC%96%91&hl=ko&gl=KR&ceid=KR:ko', 'language': 'ko'},
    {'url': 'https://news.google.com/rss/search?q=%EC%95%84%EC%8B%9C%EC%95%84%EB%A6%AC%EA%B7%B8+%EC%95%84%EC%9D%B4%EC%8A%A4%ED%95%98%ED%82%A4&hl=ko&gl=KR&ceid=KR:ko', 'language': 'ko'},
    {'url': 'https://news.google.com/rss/search?q=Asia+League+Ice+Hockey&hl=en-US&gl=US&ceid=US:en', 'language': 'en'},
    {'url': 'https://news.google.com/rss/search?q=%E3%82%A2%E3%82%B8%E3%82%A2%E3%83%AA%E3%83%BC%E3%82%B0%E3%82%A2%E3%82%A4%E3%82%B9%E3%83%9B%E3%83%83%E3%82%B1%E3%83%BC&hl=ja&gl=JP&ceid=JP:ja', 'language': 'ja'}
]

# --- 1. Supabase 클라이언트 초기화 ---
def init_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") 
    if not url or not key:
        print("Error: SUPABASE_URL or SUPABASE_SERVICE_KEY is not set.") 
        exit(1)
    return create_client(url, key)
# --- 2. DB에서 가장 최신 뉴스의 'published_at' 가져오기 (동일) ---
def get_latest_publish_time(supabase: Client) -> datetime.datetime:
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

# --- 3. 메인 파싱 및 저장 로직 (번역기 수정) ---
def main():
    supabase = init_supabase()
    
    # [수정됨] 번역기 인스턴스 생성 (deep-translator 방식)
    # source='auto' (자동 감지), target='ko' (한국어)
    translator = GoogleTranslator(source='auto', target='ko')
    
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
                    
                    original_title = entry.title
                    lang = feed['language']
                    translated_title = original_title
                    
                    # [수정됨] 번역 로직
                    if lang != 'ko':
                        try:
                            print(f"Translating from {lang}: {original_title}")
                            # [수정됨] deep-translator의 번역 호출 방식
                            translated_title = translator.translate(original_title)
                        except Exception as e:
                            print(f"Translation failed for '{original_title}', using original: {e}")
                            translated_title = original_title
                    
                    row = {
                        'title': translated_title,
                        'summary': original_title, # summary에는 항상 원본 제목
                        'origin_url': entry.link,
                        'language': lang, 
                        'published_at': entry_time_dt.isoformat(), 
                        'created_at': created_at_dt.isoformat()   
                    }
                    articles_to_insert.append(row)
                    
            except Exception as e:
                print(f"Error processing entry {entry.link}: {e}")

    # 5. 필터링된 새 뉴스만 DB에 삽입 (동일)
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