import csv
import os
from dotenv import load_dotenv
from serpapi import GoogleSearch
from datetime import datetime

load_dotenv()

# Keywords rotate 1 per category daily
KEYWORDS = {
    "fashion": ["moda", "abbigliamento", "vestiti", "scarpe", "borse", "outfit", "tendenze", "stile", "eleganti", "luxury"],
    "beauty": ["cosmetici", "makeup", "skincare", "profumi", "creme", "viso", "capelli", "bio", "naturali", "trucco"],
    "accessories": ["gioielli", "occhiali", "borse", "cinture", "orologi", "sciarpe", "portafogli", "bracciali", "anelli", "design"],
    "home": ["arredamento", "design", "mobili", "lampade", "tessili", "decorazioni", "cucine", "divani", "quadri", "vasi"]
}

params_base = {
    "engine": "google",
    "location": "Italy",
    "google_domain": "google.it",
    "hl": "it",
    "gl": "it",
    "num": 10,
    "api_key": os.getenv("SERPAPI_KEY")
}

def get_daily_keyword(category: str) -> str:
    """Get today's keyword for this category."""
    today = datetime.now().weekday()  # 0=Monday...6=Sunday
    words = KEYWORDS[category]
    return words[today % len(words)]  # Rotate daily

def write_fresh_csv(rows, filename="brands.csv"):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["URL", "Category"])
        writer.writeheader()
        writer.writerows(rows)

def generate_brands_csv(output_file: str = "brands.csv"):
    today_keywords = []
    
    # Get 1 keyword per category
    for category in KEYWORDS.keys():
        keyword = get_daily_keyword(category)
        today_keywords.append((f"site:myshopify.com \"{keyword}\"", category))
    
    print(f"📅 Today ({datetime.now().strftime('%A')}): 1 keyword/category")
    for query, cat in today_keywords:
        print(f"   🔍 {query} → {cat}")
    
    all_rows = []
    
    for query, category in today_keywords:
        params = params_base.copy()
        params["q"] = query
        
        print(f"\nSearching {category}: {query}")
        
        search = GoogleSearch(params)
        results = search.get_dict()
        organic = results.get("organic_results", [])
        
        category_rows = []
        for r in organic[:10]:
            link = (r.get("link") or "").strip()
            if link and "myshopify.com" in link:
                category_rows.append({"URL": link, "Category": category})
        
        all_rows.extend(category_rows)
        print(f"   ✅ {len(category_rows)} {category} stores")
        
        import time
        time.sleep(0.3)  # Rate limit
    
    if all_rows:
        write_fresh_csv(all_rows, output_file)
        print(f"\n✅ Fresh CSV: {len(all_rows)} leads from today's 4 keywords!")
    else:
        print("\n⚠️ No results today")

if __name__ == "__main__":
    generate_brands_csv("brands.csv")
