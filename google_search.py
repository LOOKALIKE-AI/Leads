from serpapi import GoogleSearch
import csv
import os
from dotenv import load_dotenv

load_dotenv()

# 4 predefined queries
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
    "num": 10,  # Get 10 results per query
    "api_key": os.getenv("SERPAPI_KEY")
}


def guess_category(query: str) -> str:
    """Map query directly to category."""
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


def generate_brands_csv(output_file: str = "brands.csv"):
    """
    Generates brands.csv using the first page of Google results only.
    """

    all_rows = []

    for query in QUERIES:
        params = params_base.copy()
        params["q"] = query

        search = GoogleSearch(params)
        results = search.get_dict()

        organic = results.get("organic_results", []) or []

        for r in organic[:10]:  # Max 10 per query
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