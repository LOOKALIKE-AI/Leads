from serpapi import GoogleSearch
import csv
from urllib.parse import urlparse

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
    if "fashion" in query.lower():
        return "fashion"
    elif "beauty" in query.lower():
        return "beauty"
    elif "accessories" in query.lower() or "design" in query.lower():
        return "accessories"
    elif "home" in query.lower():
        return "home"
    return "other"


# Collect all leads
all_rows = []

for query in QUERIES:
    # print(f"Searching: {query}")
    
    params = params_base.copy()
    params["q"] = query
    
    search = GoogleSearch(params)
    results = search.get_dict()
    
    organic = results.get("organic_results", [])
    
    for r in organic[:10]:  # Take max 10 per query
        link = r.get("link", "")
        category = guess_category(query)
        
        all_rows.append({
            "URL": link,
            "Category": category
        })
    
    # print(f"Found {len(organic)} results for {query}")

# Save to CSV
with open("brands.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[ "URL", "Category"])
    writer.writeheader()
    writer.writerows(all_rows)

print(f"\n Saved {len(all_rows)} total leads to brands.csv")
# print(f"Breakdown: {len([r for r in all_rows if r['Category']=='fashion'])} fashion, {len([r for r in all_rows if r['Category']=='beauty'])} beauty, etc.")
