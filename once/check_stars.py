import requests
from bs4 import BeautifulSoup
import json

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

def check_stars_list_symbols():
    url = "https://stars-kobe.com/team"
    print(f"Checking Nuxt Data: {url}")
    try:
        response = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        script = soup.find('script', id='__NUXT_DATA__')
        if script:
            print("Found __NUXT_DATA__ script.")
            try:
                data = json.loads(script.string)
                
                # Search for UUID "9ea7dacc-2116-4f86-ae75-c6dfaef80ec9"
                target_uuid = "9ea7dacc-2116-4f86-ae75-c6dfaef80ec9"
                print(f"\n--- Searching for UUID: {target_uuid} ---")
                
                for i, item in enumerate(data):
                    if item == target_uuid:
                         print(f"Found UUID at index {i}")
                         # Check neighbors (Map structure often has Key at I, Value at I+1)
                         if i + 1 < len(data):
                             print(f"  Next item (Value?): {str(data[i+1])[:200]}")
                             
                             # If value is an index, check it
                             if isinstance(data[i+1], int) and len(data) > data[i+1]:
                                 print(f"  Dereferenced Value: {data[data[i+1]]}")



            except Exception as e:
                print(f"Error parsing JSON: {e}")
    except Exception as e:
        print(f"Error checking nuxt: {e}")

if __name__ == "__main__":
    check_stars_list_symbols()
