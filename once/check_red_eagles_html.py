import requests
from bs4 import BeautifulSoup

url = "https://redeagles.co.jp/team/player/"
response = requests.get(url)
soup = BeautifulSoup(response.text, 'html.parser')

# Search for the member list container
# Note: User mentioned 'menber_list' typo in class name, let's verify.
container = soup.select_one('.menber_list')
if not container:
    print("Container '.menber_list' NOT FOUND.")
    # Try finding by section header or other common elements
    print("Searching for sections...")
    sections = soup.find_all('section')
    for s in sections:
        h2 = s.find('h2')
        if h2:
            print(f"Section found: {h2.text}")
else:
    print("Container '.menber_list' FOUND.")
    
    # Inspect first player item
    items = container.select('li')
    print(f"Found {len(items)} items.")
    
    if items:
        first_item = items[0]
        print("\n--- First Item Structure ---")
        print(first_item.prettify())
        
        # Check for links
        links = first_item.find_all('a')
        for l in links:
            print(f"Link: {l.get('href')}")

# Global search for instagram
print("\n--- Instagram Search ---")
insta_links = soup.find_all(lambda tag: tag.name == 'a' and 'instagram.com' in str(tag.get('href')))
if insta_links:
    sample = insta_links[1] # Skip the first one which is likely the team one
    print(f"Sample Insta Link: {sample.get('href')}")
    print(f"Parent: {sample.parent.name}")
    print(f"Grandparent: {sample.parent.parent.name}")
    print(f"Great-Grandparent: {sample.parent.parent.parent.name}")
    # Print the full li content of this player
    player_li = sample.find_parent('li')
    if player_li:
        print("\n--- Player LI Content ---")
        print(player_li.prettify())
