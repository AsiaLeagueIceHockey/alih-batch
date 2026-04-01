import json
import os

JERSEY_MAP = {
    "ISHIDA": 32,
    "ONODERA": 33,
    "JANG-G": 70,
    "ZAIKE": 2,
    "CHO": 7,
    "AOYAMA": 12,
    "LEE": 23,
    "WATANABE": 46,
    "KIM": 56,
    "YOO": 81,
    "ODERMATT-M": 10,
    "ODERMATT-T": 13,
    "YANO-RIN": 14,
    "YANO-RYO": 19,
    "AYRE": 22,
    "NEGISHI": 29,
    "HOU": 77,
    "JANG-H": 78,
    "PARK": 85,
    "KAWAGISHI": 86,
    "WANG": 91,
    "SHIN": 92
}

def main():
    merged_data = []
    files = ['stars_photos_batch1.json', 'stars_photos_batch2.json']
    
    for f in files:
        if os.path.exists(f):
            with open(f, 'r') as fp:
                data = json.load(fp)
                for item in data:
                    slug = item['slug']
                    if slug in JERSEY_MAP:
                        item['jersey_number'] = JERSEY_MAP[slug]
                        merged_data.append(item)
                    else:
                        print(f"Warning: No jersey found for {slug}")
        else:
            print(f"File {f} not found.")

    print(f"Enriched {len(merged_data)} players.")
    
    with open('stars_photos_final.json', 'w') as out:
        json.dump(merged_data, out, indent=2)
        
    print("Saved to stars_photos_final.json")

if __name__ == "__main__":
    main()
