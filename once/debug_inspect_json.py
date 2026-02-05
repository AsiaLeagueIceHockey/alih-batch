import json

try:
    with open('stars_nuxt_dump.json', 'r') as f:
        data = json.load(f)
    
    print(f"Loaded data: {len(data)} items")
    
    # Global search for the image ID known from subagent
    target = "268f534b" 
    
    found_indices = []
    
    for i, item in enumerate(data):
        s = str(item)
        if target in s:
            print(f"\nFOUND MATCH at Index {i}:")
            print(f"{item}")
            found_indices.append(i)
            
    if not found_indices:
        print("Target image ID NOT FOUND in global list.")
        # Try generic search for any webp
        for i, item in enumerate(data):
            if isinstance(item, str) and "storage.googleapis.com" in item:
                 print(f"Generic Image at {i}: {item}")
                 
    # Also Check Index 11 (ContentMap)
    print("\n--- Index 11 (contentMap) ---")
    if len(data) > 11:
         print(data[11])
         
except Exception as e:
    print(f"Error: {e}")
