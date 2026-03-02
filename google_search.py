import csv
import os
import json
from dotenv import load_dotenv
from serpapi import GoogleSearch

load_dotenv()

QUERIES = [
    ("site:myshopify.com 'fashion'", "fashion"),
    ("site:myshopify.com 'beauty'", "beauty"),
    ("site:myshopify.com 'Accessories / design'", "accessories"),
    ("site:myshopify.com 'Home & Living'", "home")
]

params_base = {
    "engine": "google",
    "location": "Italy",
    "google_domain": "google.it",
    "hl": "it",
    "gl": "it",
    "num": 10,
    "api_key": os.getenv("SERPAPI_KEY")
}

def load_progress() -> dict:
    """Load all category offsets from single JSON file."""
    if os.path.exists("progress.txt"):
        with open("progress.txt", "r") as f:
            data = json.load(f)
            return {k: int(v) for k, v in data.items()}
    return {"fashion": 0, "beauty": 0, "accessories": 0, "home": 0}

def save_progress(progress: dict):
    """Save all category offsets to single JSON file."""
    with open("progress.txt", "w") as f:
        json.dump(progress, f)

def write_fresh_csv(rows, filename="brands.csv"):
    """Overwrite with today's fresh leads only."""
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["URL", "Category"])
        writer.writeheader()
        writer.writerows(rows)

def generate_brands_csv(output_file: str = "brands.csv"):
    progress = load_progress()
    all_rows = []
    
    for query, category in QUERIES:
        current_start = progress[category]
        print(f"🔍 {category}: start={current_start} (page {current_start//10 + 1})")

        params = params_base.copy()
        params["q"] = query
        params["start"] = current_start

        search = GoogleSearch(params)
        results = search.get_dict()
        organic = results.get("organic_results", []) or []

        category_rows = []
        for r in organic[:10]:
            link = (r.get("link") or "").strip()
            if not link:
                continue
            category_rows.append({"URL": link, "Category": category})

        if category_rows:
            all_rows.extend(category_rows)
            print(f"   ✅ Got {len(category_rows)} new {category} leads")

        # Update this category's offset
        progress[category] = current_start + 10

    # OVERWRITE with today's fresh batch
    if all_rows:
        write_fresh_csv(all_rows, output_file)
        save_progress(progress)
        print(f"✅ Wrote {len(all_rows)} FRESH leads to {output_file}")
        print(f"📊 Progress saved: {progress}")
    else:
        print("⚠️ No results")
        save_progress(progress)

    print("➡️ Tomorrow: Next pages, fresh CSV, single progress.txt")

if __name__ == "__main__":
    generate_brands_csv("brands.csv")
