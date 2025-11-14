import os
import feedparser
import datetime
from supabase import create_client, Client
from newspaper import Article # newspaper4k 라이브러리

# --- 0. RSS 피드 목록 ---
# 사용자가 확정한 리스트
RSS_FEEDS = [
    {'url': 'https://news.google.com/rss/search?q=%EC%95%84%EC%8B%9C%EC%95%84%EB%A6%AC%EA%B7%B8+%EC%95%84%EC%9D%B4%EC%8A%A4%ED%95%98%ED%82%A4&hl=ko&gl=KR&ceid=KR:ko', 'language': 'ko'},
    {'url': 'https://news.google.com/rss/search?q=Asia+League+Ice+Hockey&hl=en-US&gl=US&ceid=US:en', 'language': 'en'},
    {'url': 'https://news.google.com/rss/search?q=%E3%82%A2%E3%82%B8%E3%82%A2%E3%83%AA%E3%83%BC%E3%82%B0%E3%82%A2%E3%82%A4%E3%82%B9%E3%83%9B%E3%83%83%E3%82%B1%E3%83%BC&hl=ja&gl=JP&ceid=JP:ja', 'language': 'ja'}
]

# --- 1. Supabase 클라이언트 초기화 ---
def init_supabase():
    """GitHub Actions Secrets에서 URL과 키를 가져와 Supabase 클라이언트를 초기화합니다."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") 
    
    if not url or not key:
        print("Error: SUPABASE_URL or SUPABASE_SERVICE_KEY is not set.") 
        exit(1)
        
    return create_client(url, key)

# --- 2. DB에서 가장 최신 뉴스의 'published_at' 가져오기 ---
def get_latest_publish_time(supabase: Client) -> datetime.datetime:
    """
    DB에 저장된 가장 최근 뉴스의 발행 시간을 가져옵니다.
    데이터가 없으면 2025-08-15를 기준으로 합니다.
    """
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
            # 타임존 정보를 포함하는 datetime 객체로 통일
            return datetime.datetime.fromisoformat('2025-08-15T00:00:00+00:00')
            
    except Exception as e:
        print(f"Error fetching latest publish time: {e}")
        return datetime.datetime.fromisoformat('2025-08-15T00:00:00+00:00')

# --- 3. [NEW] 원본 기사 본문 스크래핑 함수 ---
def get_article_text(url: str, lang: str) -> str:
    """
    newspaper4k를 사용해 원본 URL에서 기사 본문을 추출합니다.
    실패 시 None을 반환합니다.
    """
    try:
        # language 힌트를 주면 파싱 성공률이 올라갑니다.
        # user_agent를 설정하여 일부 봇 차단을 우회합니다.
        article = Article(url, language=lang)
        article.download()
        article.parse()
        return article.text
    except Exception as e:
        print(f"Failed to parse article text from {url}: {e}")
        return None

# --- 4. 메인 스크래핑 및 저장 로직 ---
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
                # RSS 피드의 발행 시간을 UTC 기준으로 datetime 객체로 변환
                entry_time_dt = datetime.datetime(*entry.published_parsed[:6], 
                                                tzinfo=datetime.timezone.utc)
                
                # DB의 최신 시간보다 더 최신인 경우에만 추가
                if entry_time_dt > latest_time:
                    
                    # DB에 삽입하는 현재 시간 (created_at 용)
                    created_at_dt = datetime.datetime.now(datetime.timezone.utc)
                    
                    # 1. 원본 기사 본문 스크래핑 시도
                    print(f"Scraping content from: {entry.link}")
                    clean_text = get_article_text(entry.link, feed['language'])
                    
                    # --- [요청사항 반영] ---
                    # 2. 스크래핑 실패 시 (clean_text가 비어있으면)
                    #    summary 필드에 'title' 값을 대신 넣습니다.
                    if not clean_text:
                        print("Scraping failed, falling back to article title.")
                        clean_text = entry.title # <--- 여기!
                    # --- [수정 완료] ---

                    row = {
                        'title': entry.title,
                        'summary': clean_text, # 본문 스크래핑 성공 시 본문, 실패 시 제목
                        'origin_url': entry.link,
                        'language': feed['language'], 
                        'published_at': entry_time_dt.isoformat(), 
                        'created_at': created_at_dt.isoformat()   
                    }
                    articles_to_insert.append(row)
                    
            except Exception as e:
                print(f"Error processing entry {entry.link}: {e}")

    # 5. 필터링된 새 뉴스만 DB에 삽입
    if articles_to_insert:
        print(f"Found {len(articles_to_insert)} new articles. Inserting to Supabase...")
        try:
            # upsert를 사용하여 origin_url이 중복되면 무시 (UNIQUE 제약 조건 필수)
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