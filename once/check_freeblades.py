import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

def check_list_page():
    url = "https://freeblades.jp/player/"
    print(f"Checking List Page: {url}")
    try:
        response = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for player items.
        # Based on common WordPress themes (Splash), might be .stm-player or different.
        # Let's search for the player name known to exist: "Ito" or "Takayuki" or "伊藤"
        
        sample_name = soup.find(string=lambda t: t and "伊藤" in t)
        if sample_name:
            print("Found sample name '伊藤'")
            title_div = sample_name.find_parent('div', class_='player-title')
            if title_div:
                # Go up to the anchor or card container
                card = title_div.find_parent('a') or title_div.find_parent('div', class_=lambda c: c and ('player' in c or 'col' in c))
                if card:
                    print("\n--- Player Card Structure ---")
                    print(card.prettify()[:1500])
                    
                    # Check for Jersey
                    jersey = card.find(string=lambda s: s and s.isdigit())
                    if jersey:
                         print(f"Potential Jersey: {jersey} inside {jersey.parent.name}")
                    else:
                        # Try finding a number class
                        num_span = card.find(class_=lambda c: c and 'number' in c)
                        if num_span:
                            print(f"Found number class: {num_span}")
        else:
            print("Sample name '伊藤' NOT FOUND.")
            # Print all div classes to guess
            divs = soup.find_all('div', class_=True)
            classes = set()
            for d in divs:
                classes.update(d['class'])
            print(f"Classes found: {list(classes)[:20]}...")

    except Exception as e:
        print(f"Error checking list: {e}")

def check_detail_page():
    url = "https://freeblades.jp/player/ito-takayuki/"
    print(f"\nChecking Detail Page: {url}")
    try:
        response = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for Instagram link
        insta_links = soup.find_all(lambda tag: tag.name == 'a' and 'instagram.com' in str(tag.get('href')))
        if insta_links:
            print(f"Found {len(insta_links)} Instagram links.")
            for l in insta_links:
                print(f"Link: {l.get('href')} - Text: {l.text.strip()}")
                print(f"Parent: {l.parent.prettify()}")
        else:
            print("No Instagram links found.")

    except Exception as e:
        print(f"Error checking detail: {e}")

if __name__ == "__main__":
    check_list_page()
    check_detail_page()
