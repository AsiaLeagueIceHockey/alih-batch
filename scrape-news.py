import os
import feedparser
import datetime
from supabase import create_client, Client
from deep_translator import GoogleTranslator

# 💡 새로 추가: 웹페이지 내용 가져오기 및 파싱
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from google import genai

# --- 0. RSS 피드 목록 ---
# 사용자가 확정한 리스트
RSS_FEEDS = [
    {'url': 'https://news.google.com/rss/search?q=HL%EC%95%88%EC%96%91&hl=ko&gl=KR&ceid=KR:ko', 'language': 'ko'},
    {'url': 'https://news.google.com/rss/search?q=%EC%95%84%EC%9D%B4%EC%8A%A4%ED%95%98%ED%82%A4&hl=ko&gl=KR&ceid=KR:ko', 'language': 'ko'},
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

# --- 3. URL 추출 함수 (Playwright 사용) ---
def get_final_url_sync(google_news_url: str) -> str:
    """
    Playwright를 사용하여 Google News URL에 접근하고, 
    JavaScript 기반 리다이렉트를 따라 최종 도착 URL을 동기적으로 반환합니다.
    """
    # 🚨 주의: GitHub Actions 환경에서는 Playwright 설치가 선행되어야 합니다.
    try:
        with sync_playwright() as p:
            # 헤드리스 모드로 Chromium 실행
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # URL로 이동 및 네트워크 활동이 잠잠해질 때까지 대기
            page.goto(google_news_url, wait_until='networkidle', timeout=30000)
            
            final_url = page.url
            browser.close()
            
            # 리다이렉션이 실패하고 Google News URL이 남아있다면 None 반환
            if 'news.google.com/rss' in final_url:
                return google_news_url # 실패 시 원래 링크 반환
                
            return final_url
            
    except Exception as e:
        print(f"Playwright URL 추출 실패 for {google_news_url}: {e}")
        return google_news_url # 오류 발생 시 원래 링크 반환

# --- 4. 웹페이지에서 텍스트 추출 함수 ---
def extract_plain_text(url: str) -> str:
    """
    주어진 URL에서 HTML을 가져와서 불필요한 태그를 제거하고 순수 텍스트만 반환합니다.
    """
    try:
        # User-Agent 설정 (curl에서 사용했던 것과 동일하게 설정하여 브라우저처럼 보이게 합니다)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
        
        # requests를 사용하여 페이지 내용을 가져옵니다. (리다이렉트 자동 처리)
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status() # HTTP 오류 발생 시 예외 발생
        
        # BeautifulSoup을 사용하여 HTML 파싱
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 스크립트, 스타일, 주석 등 불필요한 요소 제거
        for script_or_style in soup(['script', 'style', 'noscript', 'meta', 'link', 'header', 'footer', 'nav', 'form']):
            script_or_style.decompose()
            
        # <body> 태그 내의 텍스트만 추출하고, 여러 개의 공백/줄바꿈을 하나의 공백으로 치환
        text = soup.body.get_text(' ', strip=True)
        
        # 텍스트가 너무 길면 잘라내서 로깅 부담 줄이기 (예: 최대 2000자)
        MAX_TEXT_LENGTH = 2000
        if len(text) > MAX_TEXT_LENGTH:
             return text[:MAX_TEXT_LENGTH] + "..." # 일부만 반환하고 줄임표 추가
        
        return text

    except requests.exceptions.RequestException as e:
        return f"[Error fetching content]: {e}"
    except Exception as e:
        return f"[Error parsing content]: {e}"

# --- 4.5 Gemini 요약 함수 ---
def get_ai_summary(text: str) -> str:
    """
    Gemini API를 사용하여 텍스트를 한국어로 80자 이내로 요약합니다.
    """
    # The client gets the API key from the environment variable `GEMINI_API_KEY`.
    # api_key 체크는 client 내부에서 처리되거나 환경변수 없을 시 에러 발생 가능하므로
    # 안전하게 환경변수 확인 후 진행
    if not os.environ.get("GEMINI_API_KEY"):
        print("Warning: GEMINI_API_KEY is not set. Skipping summary.")
        return ""
    
    try:
        client = genai.Client()
        
        # 입력 텍스트가 너무 길면 앞부분만 사용 (비용/속도 최적화)
        input_text = text[:4000] if len(text) > 4000 else text
        
        prompt = (
            "다음 뉴스 기사를 한국어로 읽기 쉽게 80자 이내로 요약해줘. "
            "기계적인 번역투보다는 자연스러운 한국어 뉴스 헤드라인이나 요약문처럼 작성해줘. "
            "결과는 요약된 텍스트만 출력해:\n\n"
            f"{input_text}"
        )
        
        response = client.models.generate_content(
            model="gemini-2.5-flash", contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print(f"Gemini summary failed: {e}")
        return ""

# --- 5. 메인 파싱 및 저장 로직 (수정) ---
def main():
    supabase = init_supabase()
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
                    
                    # 💡 URL 추출: entry.link (Google News RSS URL)을 사용
                    # ----------------------------------------------------
                    google_link = entry.link
                    # 1. 최종 원본 URL을 추출합니다.
                    origin_url = get_final_url_sync(google_link)
                    
                    if origin_url == google_link:
                        print(f"Warning: Failed to extract final URL for: {google_link}")
                    else:
                        print(f"Success: Extracted URL: {origin_url}")
                    # ----------------------------------------------------
                    
                    # 💡 새로 추가된 부분: 원본 URL에서 텍스트 추출
                    # ----------------------------------------------------
                    article_content_text = extract_plain_text(origin_url)
                    
                    # 💡 추출된 텍스트 로깅
                    print("\n--- Extracted Article Text (First 2000 chars) ---")
                    print(article_content_text)
                    print("---------------------------------------------------\n")
                    
                    # ----------------------------------------------------
                    
                    # 💡 Gemini를 이용한 요약 (내용이 충분히 있을 때만)
                    summary_text = ""
                    if article_content_text and len(article_content_text) > 100:
                        print("Summarizing article with Gemini...")
                        summary_text = get_ai_summary(article_content_text)
                        if summary_text:
                            print(f"Summary: {summary_text}")
                    
                    # 요약 실패하거나 내용이 없으면 원본 제목 사용
                    if not summary_text:
                        summary_text = original_title

                    translated_title = original_title
                    
                    # (번역 로직 생략 - 기존과 동일)
                    if lang != 'ko':
                        try:
                            # ... (번역 코드) ...
                            print(f"Translating from {lang}: {original_title}")
                            translated_title = translator.translate(original_title)
                        except Exception as e:
                            print(f"Translation failed for '{original_title}', using original: {e}")
                            translated_title = original_title
                    
                    row = {
                        'title': translated_title,
                        'summary': summary_text, # 💡 수정: AI 요약본 사용
                        'origin_url': origin_url,  # 💡 수정: 추출된 최종 URL 사용
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