import os
import re
import requests
from typing import Dict, Any
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv

from urllib.parse import urlsplit, urlunsplit



load_dotenv()

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
FATTURATO_RE = re.compile(
    r"(?i)\bfatturato\b\s*:\s*(?:€\s*)?([0-9\.\,]+)\s*(?:€)?\s*(?:\((\d{4})\))?"
)
YEAR_RE = re.compile(r"\((\d{4})\)")

def _normalize_it_number(s: str) -> str:
    # "269.674,00" -> "269674.00"
    return s.strip().replace(".", "").replace(",", ".")

def _strip_query_params(url: str) -> str:
    # remove ?srsltid=... etc.
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

def get_fatturato_from_piva(piva: str) -> Dict[str, Any]:
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        raise ValueError("Missing SERPAPI_API_KEY env var.")

    piva_digits = re.sub(r"\D", "", piva)
    query = f"{piva_digits} fatturato"

    # 1) SERP: first organic link
    params = {
        "engine": "google",
        "q": query,
        "api_key": api_key,
        "google_domain": "google.it",
        "gl": "it",
        "hl": "it",
        "num": 10,
    }
    serp_resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=30)
    serp_resp.raise_for_status()
    serp_data = serp_resp.json()

    organic = serp_data.get("organic_results") or []
    if not organic or not organic[0].get("link"):
        return {"found": False, "reason": "No organic results", "source_url": None}

    raw_url = organic[0]["link"]
    url = _strip_query_params(raw_url)

    # 2) Open with Playwright (more realistic context + waits + fallback)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            locale="it-IT",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
            },
        )

        page = context.new_page()

        try:
            # networkidle helps when content is rendered after initial load
            page.goto(url, wait_until="networkidle", timeout=45000)
        except PlaywrightTimeoutError:
            # If networkidle times out, still continue and try parsing what we have
            pass

        # Quick bot-check detection (common with Cloudflare)
        title = (page.title() or "").lower()
        html_now = page.content().lower()
        if "just a moment" in title or "cf-" in html_now or "cloudflare" in html_now:
            browser.close()
            return {
                "found": False,
                "reason": "Blocked by bot protection (Cloudflare page loaded)",
                "source_url": url,
            }

        # Wait for the specific block you saw in DevTools
        try:
            page.wait_for_selector("ul#first-group", timeout=15000)
        except PlaywrightTimeoutError:
            # Not fatal — fallback to regex on full page text
            pass

        # Try exact selector (your DOM)
        li = page.locator("ul#first-group li.list-group-item", has_text="Fatturato").first
        if li.count() > 0:
            # Value is inside <strong>
            strong = li.locator("strong").first
            if strong.count() > 0:
                amount_text = strong.inner_text().strip()
                full_text = li.inner_text()
                y = YEAR_RE.search(full_text)
                year_found = int(y.group(1)) if y else None

                browser.close()
                return {
                    "found": True,
                    "fatturato_eur": _normalize_it_number(amount_text),
                    "fatturato_raw": amount_text,
                    "year": year_found,
                    "source_url": url,
                }

        # Fallback: regex scan whole page text
        page_text = " ".join(page.inner_text("body").split())
        m = FATTURATO_RE.search(page_text)

        browser.close()

        if not m:
            return {
                "found": False,
                "reason": "Fatturato not found (selector + regex failed)",
                "source_url": url,
            }

        amount_raw = m.group(1)
        year_raw = m.group(2)
        return {
            "found": True,
            "fatturato_eur": _normalize_it_number(amount_raw),
            "fatturato_raw": amount_raw,
            "year": int(year_raw) if year_raw else None,
            "source_url": url,
        }


# Example:
print(get_fatturato_from_piva("11814320963"))