import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

def check_icebucks_list():
    url = "https://www.icebucks.jp/players/"
    print(f"Checking List Page: {url}")
    try:
        response = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for player identification. 
        # Often lists are in <li> or <div> with class 'player'
        
        # Find ul.member-list
        ul = soup.find('ul', class_='member-list')
        if ul:
            print("Found ul.member-list")
            items = ul.find_all('li')
            print(f"Found {len(items)} items.")
            
            if items:
                sample = items[0]
                print("\n--- Sample Item ---")
                print(sample.prettify()[:2000])
                
                # Check for links
                links = sample.find_all('a')
                for l in links:
                    print(f"Link: {l.get('href')} | Title: {l.get('title')}")
                    
                # Check for Name (often in h3, p, or div)
                print("\n--- Text Content ---")
                print(sample.get_text(separator=' | ', strip=True))

    except Exception as e:
        print(f"Error checking list: {e}")

if __name__ == "__main__":
    check_icebucks_list()
