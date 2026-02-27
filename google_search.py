from google_search_results import GoogleSearch
import csv
import os
import datetime
from dotenv import load_dotenv

load_dotenv()

QUERIES = [
    "site:myshopify.com 'fashion'",
    "site:myshopify.com 'beauty'",
    "site:myshopify.com 'Accessories / design'",
    "site:myshopify.com 'Home & Living'"
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


def guess_category(query: str) -> str:
    q = query.lower()
    if "fashion" in q:
        return "fashion"
    elif "beauty" in q:
        return "beauty"
    elif "accessories" in q or "design" in q:
        return "accessories"
    elif "home" in q:
        return "home"
    return "other"


def get_daily_start_offset(total_pages: int = 40) -> int:
    """
    Rotates through 40 SERP pages.
    
    Day 1 -> page 0 (start=0)
    Day 2 -> page 1 (start=10)
    ...
    Day 40 -> page 39 (start=390)
    Day 41 -> page 0 again
    """
    today = datetime.date.today()
    page_number = today.toordinal() % total_pages
    return page_number * 10


def generate_brands_csv(output_file: str = "brands.csv"):
    """
    Generates brands.csv using rotating SERP pagination.
    Each day pulls the next page of Google results.
    """

    all_rows = []

    # start_offset = get_daily_start_offset(total_pages=40)
    start_offset = 10

    print(f"🔁 Using SERP page offset: {start_offset}")

    for query in QUERIES:
        params = params_base.copy()
        params["q"] = query
        params["start"] = start_offset  # ✅ Rotating page

        search = GoogleSearch(params)
        results = search.get_dict()

        organic = results.get("organic_results", []) or []

        for r in organic:
            link = (r.get("link") or "").strip()
            if not link:
                continue

            all_rows.append({
                "URL": link,
                "Category": guess_category(query)
            })

    # Save CSV
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["URL", "Category"])
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"✅ Saved {len(all_rows)} total leads to {output_file}")