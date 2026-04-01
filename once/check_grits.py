import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

def check_grits_list():
    url = "https://grits-sport.com/players"
    print(f"Checking List Page: {url}")
    try:
        response = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Determine player card structure
        # User example detail: https://grits-sport.com/player/11301
        # Look for links containing 'player/'
        
        cards = soup.find_all('a', href=lambda h: h and '/player/' in h)
        print(f"Found {len(cards)} potential player links.")
        
        if cards:
            sample = cards[0]
            print("\n--- Sample Player Link ---")
            print(sample.prettify()[:500])
            
            # Go up to find the container
            # Try 1 level up
            parent = sample.parent
            if parent:
                print("\n--- Parent Element ---")
                print(parent.prettify()[:1000])
                
                # Try 2 levels up
                grandparent = parent.parent
                if grandparent:
                    print("\n--- Grandparent Element ---")
                    print(grandparent.prettify()[:1000])
                    
            # Try to find text siblings
            print("\n--- Siblings or nearby text ---")
            # Usually structure is Image -> Name -> Jersey or similar
            # Iterate siblings
            for sib in sample.next_siblings:
                if sib.name:
                    print(f"Sibling: {sib.name} | Text: {sib.get_text().strip()}")

    except Exception as e:
        print(f"Error checking list: {e}")

def check_grits_detail():
    # User provided example
    url = "https://grits-sport.com/player/11301" 
    print(f"\nChecking Detail Page: {url}")
    try:
        response = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for Instagram
        insta_links = soup.find_all(lambda tag: tag.name == 'a' and 'instagram.com' in str(tag.get('href')))
        for l in insta_links:
            print(f"Insta Link: {l.get('href')} - Parent: {l.parent.name} ({l.parent.get('class')})")
            
    except Exception as e:
        print(f"Error checking detail: {e}")

if __name__ == "__main__":
    check_grits_list()
    check_grits_detail()
