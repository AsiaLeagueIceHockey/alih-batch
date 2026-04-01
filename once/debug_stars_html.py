import requests
from bs4 import BeautifulSoup
import json
import re

url = "https://stars-kobe.com/ISHIDA"
resp = requests.get(url)
soup = BeautifulSoup(resp.text, 'html.parser')

script = soup.find('script', id='__NUXT_DATA__')
if not script:
    print("No __NUXT_DATA__ found")
    exit()

try:
    data = json.loads(script.string)
    print("JSON parsed successfully.")
    
    # Recursive search for image urls
    found_images = []
    
    def search(obj, path="root"):
        if isinstance(obj, dict):
            for k, v in obj.items():
                search(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                search(v, f"{path}[{i}]")
        elif isinstance(obj, str):
            if "storage.googleapis.com" in obj and (".webp" in obj or ".jpg" in obj or ".png" in obj):
                found_images.append((path, obj))
    
    search(data)
    
    print(f"\nFound {len(found_images)} potential images:")
    for path, img in found_images:
        print(f"{path}: {img}")

except Exception as e:
    print(f"Error parsing JSON: {e}")
