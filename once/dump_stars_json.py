import requests
from bs4 import BeautifulSoup
import json

url = "https://stars-kobe.com/ISHIDA"
resp = requests.get(url)
soup = BeautifulSoup(resp.text, 'html.parser')

script = soup.find('script', id='__NUXT_DATA__')
if script:
    try:
        data = json.loads(script.string)
        with open('stars_nuxt_dump.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("Dropped raw JSON to stars_nuxt_dump.json")
    except Exception as e:
        print(f"JSON Parse Error: {e}")
else:
    print("No __NUXT_DATA__ found")
