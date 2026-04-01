import asyncio
from playwright.async_api import async_playwright

async def get_final_url_via_browser(google_news_url: str) -> str:
    """
    Playwright를 사용하여 Google News URL에 접근하고, 
    JavaScript 기반 리다이렉트를 따라 최종 도착 URL을 반환합니다.
    """
    print("브라우저를 시작하고 최종 URL을 찾습니다. (시간이 다소 소요될 수 있습니다...)")
    async with async_playwright() as p:
        # 브라우저 실행 (headless=True는 화면에 브라우저를 띄우지 않음을 의미)
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Google News URL로 이동
        # wait_until='networkidle' 옵션을 사용하여 네트워크 활동이 잠잠해질 때까지 기다립니다.
        # 이는 JS 리다이렉트가 완료되기를 기다리는 데 도움이 됩니다.
        try:
            await page.goto(google_news_url, wait_until='networkidle', timeout=30000)
            
            # 리다이렉션이 발생한 후, 브라우저가 최종적으로 도착한 URL을 가져옵니다.
            final_url = page.url
            
            await browser.close()
            return final_url
            
        except Exception as e:
            await browser.close()
            return f"페이지 로딩 중 오류 발생 또는 타임아웃: {e}"

# ----------------------------------------------------
# 사용 예시
# ----------------------------------------------------
target_url = 'https://news.google.com/rss/articles/CBMiWkFVX3lxTE5rcXNjcThrRENUaWZSelh5cmlQT3BmWTR0Q0pIN3hpZHg2MXY0dUpDVTZIV1Z2c1dpLVROQkNRb2NSa1R5amNIR183ZnVqelJCY0FoeG9xTXplZw?oc=5'

# 비동기 함수 실행
final_url = asyncio.run(get_final_url_via_browser(target_url))

print(f"\n요청 URL: {target_url}")
print(f"**추출된 최종 원본 URL:** {final_url}")