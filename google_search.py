import csv
import os
import time
from datetime import datetime

from dotenv import load_dotenv
from serpapi import GoogleSearch

load_dotenv()

KEYWORDS = {
    "fashion": [
        "clothing", "apparel", "dresses", "shoes", "bags",
        "outfits", "trendy", "style", "luxury", "designer"
    ],
    "beauty": [
        "beauty", "makeup", "cosmetics", "skincare", "perfume",
        "cream", "face", "lips", "eyes", "organic"
    ],
    "accessories": [
        "jewelry", "sunglasses", "handbags", "belts", "watches",
        "scarves", "wallets", "bracelets", "rings", "vintage"
    ],
    "home": [
        "home", "furniture", "decor", "lamps", "rugs",
        "pillows", "art", "vases", "sofas", "kitchen"
    ],
}


def get_api_key() -> str:
    api_key = os.getenv("SERPAPI_KEY", "").strip()
    if not api_key:
        raise ValueError("SERPAPI_KEY is missing. Add it in GitHub Secrets.")
    return api_key


def get_daily_keyword(category: str) -> str:
    today_index = datetime.now().weekday()  # 0 = Monday, 6 = Sunday
    words = KEYWORDS[category]
    return words[today_index % len(words)]


def write_fresh_csv(rows, filename="brands.csv"):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["URL", "Category"])
        writer.writeheader()
        writer.writerows(rows)


def search_myshopify_stores(query: str, category: str, api_key: str):
    params = {
        "engine": "google",
        "q": query,
        "location": "Italy",
        "google_domain": "google.it",
        "hl": "it",
        "gl": "it",
        "num": 10,
        "api_key": api_key,
    }

    print(f"\nSearching {category}: {query}")

    search = GoogleSearch(params)
    results = search.get_dict()

    if "error" in results:
        raise RuntimeError(f"SerpAPI error: {results['error']}")

    organic = results.get("organic_results", [])
    rows = []

    for result in organic:
        link = (result.get("link") or "").strip()
        if "myshopify.com" in link:
            rows.append({
                "URL": link,
                "Category": category,
            })

    print(f"   ✅ {len(rows)} {category} stores found (organic results: {len(organic)})")
    return rows


def deduplicate_rows(rows):
    seen = set()
    unique_rows = []

    for row in rows:
        key = (row["URL"], row["Category"])
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)

    return unique_rows


def generate_brands_csv(output_file="brands.csv"):
    api_key = get_api_key()
    print("🔑 API Key loaded: ✅ YES")

    today_queries = []
    for category in KEYWORDS:
        keyword = get_daily_keyword(category)
        query = f'site:myshopify.com "{keyword}"'
        today_queries.append((query, category))

    print(f"📅 Today ({datetime.now().strftime('%A')}): 1 keyword per category")
    for query, category in today_queries:
        print(f"   🔍 {query} → {category}")

    all_rows = []

    for query, category in today_queries:
        try:
            category_rows = search_myshopify_stores(query, category, api_key)
            all_rows.extend(category_rows)
        except Exception as e:
            print(f"❌ Error for {category}: {e}")

        time.sleep(1)

    all_rows = deduplicate_rows(all_rows)

    if all_rows:
        write_fresh_csv(all_rows, output_file)
        print(f"\n✅ Fresh CSV written: {len(all_rows)} unique leads saved to {output_file}")
    else:
        print("\n⚠️ No results found today")
        write_fresh_csv([], output_file)
        print(f"📝 Empty CSV created: {output_file}")


if __name__ == "__main__":
    generate_brands_csv("brands.csv")
