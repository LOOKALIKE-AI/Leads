import csv
import time
import re
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from dotenv import load_dotenv
from serpapi import GoogleSearch

# ============================================================
# ENV + GLOBALS
# ============================================================

load_dotenv()
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

PHONE_RE = re.compile(
    r"(?:(?:\+|00)\s?39\s?)?"
    r"(?:0\d{1,3}|\d{3,4})"
    r"[\s./-]?\d{2,4}"
    r"(?:[\s./-]?\d{2,4}){1,3}"
)

VAT_RE = re.compile(r"\b(?:IT\s*)?(\d{11})\b", re.IGNORECASE)

# “PMI” in your request = legal structure detected (company-type keywords)
LEGAL_STRUCT_RE = re.compile(
    r"\b("
    r"s\.?\s*r\.?\s*l\.?|"
    r"s\.?\s*p\.?\s*a\.?|"
    r"s\.?\s*a\.?\s*s\.?|"
    r"s\.?\s*n\.?\s*c\.?|"
    r"unipersonale|"
    r"societ[aà]\s+cooperativa|coop\.?|"
    r"ltd|limited|llc|inc\.?|incorporated|corp\.?|gmbh|pty"
    r")\b",
    re.IGNORECASE
)

# ============================================================
# BASIC HELPERS
# ============================================================

def extract_domain(url: str):
    try:
        parsed = urlparse(url.strip())
        domain = (parsed.netloc or "").lower().replace("www.", "")
        return domain or None
    except Exception:
        return None

def safe_get(url: str, timeout=15):
    """Return Response only if status_code == 200, else None."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r is not None and r.status_code == 200:
            return r
        return None
    except Exception:
        return None

# ============================================================
# BRAND (TITLE TAG ONLY, as requested)
# ============================================================
def extract_brand_from_title(soup: BeautifulSoup, url: str = "") -> str:
    """
    Extract clean brand name from <title>.

    Logic:
    1. Split title by common separators.
    2. Prefer the shortest meaningful segment (likely the brand).
    3. Remove ecommerce junk words.
    4. Fallback to domain if needed.
    """

    title_tag = soup.find("title")
    if not title_tag:
        return ""

    raw_title = title_tag.get_text(" ", strip=True)
    raw_title = re.sub(r"\s+", " ", raw_title).strip()

    # Split by common separators
    parts = re.split(r"\s*[\|\-–•·:]\s*", raw_title)

    # Words that usually indicate product/category text
    junk_words = [
        "shop", "store", "official", "online", "acquista", "buy",
        "spedizione", "free shipping", "sale", "sconto",
        "collezione", "collection", "scarpe", "uomo", "donna",
        "home", "homepage"
    ]

    candidates = []

    for part in parts:
        clean = part.strip()

        # Skip very long strings (likely product names)
        if len(clean) > 60:
            continue

        # Skip if too short
        if len(clean) < 2:
            continue

        lower = clean.lower()

        # Skip segments full of junk words
        if any(word in lower for word in junk_words):
            continue

        candidates.append(clean)

    # If we found good candidates → choose the shortest (usually brand)
    if candidates:
        brand = min(candidates, key=len)
        return brand.strip()

    # Fallback: use shortest part overall
    if parts:
        fallback = min(parts, key=len).strip()
        if 2 <= len(fallback) <= 60:
            return fallback

    # Final fallback: domain
    if url:
        domain = urlparse(url).netloc.replace("www.", "")
        return domain.split(".")[0].title()

    return ""


# ============================================================
# SKU COUNT (best-effort)
# ============================================================

def count_skus(base_url: str, soup: BeautifulSoup) -> int:
    """
    Estimate SKU count from /collections/all (Shopify-ish).
    If not available, fallback to homepage product-ish links.
    """
    try:
        collections_url = urljoin(base_url, "/collections/all")
        r = safe_get(collections_url, timeout=12)
        if r:
            coll_soup = BeautifulSoup(r.text, "html.parser")
            product_selectors = [
                'a[href*="/products/"]',
                ".product-item",
                ".product-card",
                ".grid-item",
                "[data-product-id]"
            ]
            max_count = 0
            for selector in product_selectors:
                max_count = max(max_count, len(coll_soup.select(selector)))

            if max_count > 0:
                # crude multiplier for pagination; capped
                return min(max_count * 3, 1000)

        product_links = soup.find_all("a", href=re.compile(r"/products?/"))
        return min(len(product_links), 500)
    except Exception:
        return 0

# ============================================================
# TEXT ONLY SEARCH + UX
# ============================================================

def has_text_only_search(soup: BeautifulSoup) -> str:
    search_inputs = (
        soup.find("input", {"type": "search"}) or
        soup.find("input", {"name": re.compile(r"q|search|query", re.I)}) or
        soup.find("input", {"placeholder": re.compile(r"search|cerca|find", re.I)}) or
        soup.find("input", {"id": re.compile(r"search|query", re.I)})
    )

    all_text = soup.get_text(" ", strip=True).lower()
    search_texts = ["search", "cerca", "ricerca", "trova"]

    ecommerce_indicators = [
        "/products/", "add to cart", "aggiungi al carrello",
        "price", "prezzo", "buy now", "acquista"
    ]

    has_search = bool(search_inputs) or any(t in all_text for t in search_texts)
    has_products = any(ind in all_text for ind in ecommerce_indicators)

    return "Y" if has_search and has_products else "N"

def has_refined_ux(soup: BeautifulSoup) -> str:
    checks = 0
    if soup.find(["nav", "header"]) is not None:
        checks += 1
    if soup.find("footer") is not None:
        checks += 1
    if soup.find_all(["section", "div"], class_=re.compile(r"product|grid|collection", re.I)):
        checks += 1
    nav_links = soup.find("nav") or soup.find("ul", class_=re.compile(r"menu|nav", re.I))
    if nav_links and len(nav_links.find_all("a")) > 3:
        checks += 1
    return "Y" if checks >= 2 else "N"

# ============================================================
# CONTACT EXTRACTION
# ============================================================

def _normalize_phone(p: str) -> str:
    p = re.sub(r"\s+", " ", (p or "")).strip()
    return p.rstrip(".,;:")

def _extract_mailto_tel(soup: BeautifulSoup):
    emails, phones = set(), set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        h = href.lower()
        if h.startswith("mailto:"):
            e = href.split(":", 1)[1].split("?", 1)[0].strip()
            if e:
                emails.add(e)
        elif h.startswith("tel:"):
            p = href.split(":", 1)[1].strip()
            if p:
                phones.add(_normalize_phone(p))
    return emails, phones

def _extract_from_text(soup: BeautifulSoup):
    emails, phones = set(), set()
    text = soup.get_text(" ", strip=True)

    for e in EMAIL_RE.findall(text):
        if not any(x in e.lower() for x in ["example.com", "sentry", "google", "shopify"]):
            emails.add(e)

    for p in PHONE_RE.findall(text):
        p2 = _normalize_phone(p)
        if len(re.sub(r"\D", "", p2)) >= 8:
            phones.add(p2)

    return emails, phones

def _extract_from_jsonld(soup: BeautifulSoup):
    emails, phones = set(), set()
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for s in scripts:
        raw = (s.string or "").strip()
        if not raw:
            continue
        for e in EMAIL_RE.findall(raw):
            emails.add(e)
        for p in PHONE_RE.findall(raw):
            phones.add(_normalize_phone(p))
    return emails, phones

def _extract_obfuscated_emails(html: str):
    emails = set()
    patterns = [
        r"([A-Za-z0-9._%+-]+)\s*\[?\(?\s*at\s*\)?\]?\s*([A-Za-z0-9.-]+)\s*\[?\(?\s*dot\s*\)?\]?\s*([A-Za-z]{2,})",
        r"([A-Za-z0-9._%+-]+)\s*\(at\)\s*([A-Za-z0-9.-]+)\s*\(dot\)\s*([A-Za-z]{2,})",
    ]
    for pat in patterns:
        for m in re.findall(pat, html, flags=re.IGNORECASE):
            emails.add(f"{m[0]}@{m[1]}.{m[2]}")
    return emails

def _discover_contactish_links(soup: BeautifulSoup, base_url: str, limit=10):
    keywords = [
        "contatti", "contatto", "contact", "assistenza", "supporto",
        "help", "resi", "sped", "shipping",
        "privacy", "termini", "condizioni", "impressum", "chi-siamo", "about",
        "note legali", "legal"
    ]
    links, seen = [], set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = (a.get_text() or "").strip().lower()
        blob = (href + " " + text).lower()

        if any(k in blob for k in keywords):
            full = urljoin(base_url, href)
            try:
                if urlparse(full).netloc == urlparse(base_url).netloc:
                    if full not in seen:
                        seen.add(full)
                        links.append(full)
            except Exception:
                continue

        if len(links) >= limit:
            break

    return links

def _candidate_shopify_paths(base_url: str):
    # Shopify common pages
    paths = [
        "/pages/contatti",
        "/pages/contatto",
        "/pages/contattaci",
        "/pages/contact",
        "/pages/contact-us",
        "/pages/assistenza",
        "/pages/supporto",
        "/pages/servizio-clienti",
        "/pages/chi-siamo",
        "/pages/about-us",
        "/policies/privacy-policy",
        "/policies/terms-of-service",
        "/policies/refund-policy",
        "/policies/shipping-policy",
    ]
    return [urljoin(base_url, p) for p in paths]

def extract_contact_info(url: str, soup: BeautifulSoup, html: str, max_pages: int = 10, sleep_s: float = 0.6):
    emails, phones = set(), set()

    # homepage
    e1, p1 = _extract_mailto_tel(soup)
    e2, p2 = _extract_from_text(soup)
    e3, p3 = _extract_from_jsonld(soup)
    e4 = _extract_obfuscated_emails(html)

    emails |= (e1 | e2 | e3 | e4)
    phones |= (p1 | p2 | p3)

    # other pages
    pages = _discover_contactish_links(soup, url, limit=max_pages) + _candidate_shopify_paths(url)

    # de-dupe
    seen = set()
    unique_pages = []
    for p in pages:
        if p not in seen:
            seen.add(p)
            unique_pages.append(p)
    unique_pages = unique_pages[:max_pages]

    # crawl if still missing
    if (not emails) or (not phones):
        for purl in unique_pages:
            time.sleep(sleep_s)
            r = safe_get(purl, timeout=12)
            if not r:
                continue

            csoup = BeautifulSoup(r.text, "html.parser")

            ce1, cp1 = _extract_mailto_tel(csoup)
            ce2, cp2 = _extract_from_text(csoup)
            ce3, cp3 = _extract_from_jsonld(csoup)
            ce4 = _extract_obfuscated_emails(r.text)

            emails |= (ce1 | ce2 | ce3 | ce4)
            phones |= (cp1 | cp2 | cp3)

            if emails and phones:
                break

    email = sorted(emails)[0] if emails else ""
    phone = sorted(phones)[0] if phones else ""
    return email, phone

# ============================================================
# VAT + PMI (LEGAL STRUCTURE)
# ============================================================

def extract_vat_numbers(text: str):
    if not text:
        return []
    vats = VAT_RE.findall(text)
    vats = [v.strip() for v in vats if v and len(v.strip()) == 11]
    seen = set()
    out = []
    for v in vats:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out

def pmi_detected(text: str) -> str:
    """PMI = company/legal structure keywords detected."""
    if not text:
        return "N"
    return "Y" if LEGAL_STRUCT_RE.search(text) else "N"

# ============================================================
# FATTURATO (REVENUE VALUE) via SERPAPI
# ============================================================

MONEY_RE = re.compile(
    r"(?P<cur>€)?\s*(?P<num>\d[\d\.\,]*)\s*"
    r"(?P<unit>mld|miliard[oi]|bn|billion|mln|milion[ei]|milioni|million|m|k|mila)?",
    re.IGNORECASE
)
KEYWORDS_RE = re.compile(r"\b(fatturato|ricavi|turnover)\b", re.IGNORECASE)

def _parse_eur_amount(text: str):
    if not text:
        return None

    m = MONEY_RE.search(text)
    if not m:
        return None

    raw_num = (m.group("num") or "").strip()
    unit = (m.group("unit") or "").lower().strip()

    # normalize IT/EN number formats
    if "." in raw_num and "," in raw_num:
        s = raw_num.replace(".", "").replace(",", ".")
    elif "," in raw_num:
        if re.match(r"^\d{1,3},\d{1,2}$", raw_num):
            s = raw_num.replace(",", ".")
        else:
            s = raw_num.replace(",", "")
    else:
        if re.match(r"^\d{1,3}(\.\d{3})+$", raw_num):
            s = raw_num.replace(".", "")
        else:
            s = raw_num

    try:
        value = float(s)
    except Exception:
        return None

    multiplier = 1
    if unit in ("k", "mila"):
        multiplier = 1_000
    elif unit in ("m", "mln", "milione", "milioni", "million"):
        multiplier = 1_000_000
    elif unit in ("mld", "miliardo", "miliardi", "bn", "billion"):
        multiplier = 1_000_000_000

    return value * multiplier

def get_revenue_from_serpapi(vat_number: str):
    """
    Returns revenue_eur (float) or None.
    """
    if not SERPAPI_KEY:
        return None

    vat_digits = "".join(ch for ch in (vat_number or "") if ch.isdigit())
    if len(vat_digits) != 11:
        return None

    params = {
        "engine": "google",
        "q": f'"{vat_digits}" (fatturato OR ricavi OR turnover)',
        "location": "Italy",
        "hl": "it",
        "gl": "it",
        "num": 1,
        "api_key": SERPAPI_KEY
    }

    try:
        results = GoogleSearch(params).get_dict()
    except Exception:
        return None

    for result in results.get("organic_results", []):
        snippet = result.get("snippet", "") or ""
        if not KEYWORDS_RE.search(snippet.lower()):
            continue

        revenue = _parse_eur_amount(snippet)
        if revenue and revenue > 0:
            return revenue

    return None

# ============================================================
# SIZE (FROM FATTURATO VALUE)
# ============================================================

def size_from_fatturato(revenue_eur):
    if revenue_eur is None:
        return "UNKNOWN"
    try:
        revenue = float(revenue_eur)
    except (ValueError, TypeError):
        return "UNKNOWN"

    if revenue < 500_000:
        return "MICRO"
    elif revenue < 2_000_000:
        return "SMALL"
    elif revenue < 10_000_000:
        return "MEDIUM"
    elif revenue < 50_000_000:
        return "LARGE"
    else:
        return "ENTERPRISE"

# ============================================================
# SCORE 0-5 (SKU, TEXT SEARCH, UX, PMI, SIZE)
# ============================================================

def calculate_score(sku: int, text_search: str, ux: str, pmi: str, size: str) -> int:
    """
    Score range: 0 - 5

    +1 if SKU >= 200
    +1 if Text Only Search == "Y"
    +1 if UX Designed == "Y"
    +1 if PMI == "Y"
    +1 if Size in ("MEDIUM", "LARGE", "ENTERPRISE")

    All conditions are binary.
    No partial points.
    """

    score = 0

    # SKU condition
    if sku >= 200:
        score += 1

    # Text search condition
    if text_search == "Y":
        score += 1

    # UX condition
    if ux == "Y":
        score += 1

    # PMI condition
    if pmi == "Y":
        score += 1

    # Size condition
    if size in ("MEDIUM", "LARGE", "ENTERPRISE"):
        score += 1

    return score  # already guaranteed 0–5



def priority_from_score(score: int) -> str:
    try:
        s = int(score)
    except Exception:
        return "LOW"
    return "LOW" if s <= 2 else "HIGH"


# ============================================================
# MAIN EXTRACTION
# ============================================================

def process_store(url: str, category: str):
    print(f"🔍 Processing: {url}")

    r = safe_get(url, timeout=15)
    if not r:
        print(f"❌ Failed: {url}")
        return None

    html = r.text
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    brand = extract_brand_from_title(soup)
    sku = count_skus(url, soup)
    text_search = has_text_only_search(soup)
    ux = has_refined_ux(soup)

    email, phone = extract_contact_info(url, soup, html, max_pages=10, sleep_s=0.6)

    vats = extract_vat_numbers(page_text)
    pmi = pmi_detected(page_text)

    revenue_eur = None
    if vats:
        revenue_eur = get_revenue_from_serpapi(vats[0])

    size = size_from_fatturato(revenue_eur)
    score = calculate_score(sku, text_search, ux, pmi, size)
    priority = priority_from_score(score)

    return {
        "brand": brand,
        "url": url,
        "category": category.strip(),
        "sku": sku,
        "Text Only Search": text_search,
        "UX Designed": ux,
        "PMI": pmi,
        "Fatturato": revenue_eur if revenue_eur is not None else "",
        "Size": size,
        "Score 0-5": score,
        "Platform": "Shopify",  # per your requirement
        "Email": email,
        "Tel": phone,
        "Priority": priority,  
    }

# ============================================================
# BATCH PROCESSOR
# ============================================================

def run(input_csv: str, output_csv: str = "leads.csv", sleep_s: float = 1.5):
    seen_domains = set()
    results = []

    with open(input_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        url_col = next((col for col in reader.fieldnames if "url" in col.lower()), None)
        cat_col = next((col for col in reader.fieldnames if "category" in col.lower() or "cat" in col.lower()), None)

    if not url_col:
        raise ValueError("Need a URL column (contains 'url' in header).")

    with open(input_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = (row.get(url_col) or "").strip()
            category = (row.get(cat_col) or "unknown").strip() if cat_col else "unknown"

            if not url.startswith(("http", "https")):
                continue

            domain = extract_domain(url)
            if domain and domain in seen_domains:
                continue
            if domain:
                seen_domains.add(domain)

            result = process_store(url, category)
            if result:
                results.append(result)

            time.sleep(sleep_s)

    fieldnames = [
        "brand",
        "url",
        "category",
        "sku",
        "Text Only Search",
        "UX Designed",
        "PMI",
        "Fatturato",
        "Size",
        "Score 0-5",
        "Platform",
        "Email",
        "Tel",
        "Priority",
    ]

    if results:
        with open(output_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        print(f"\n✅ Saved {len(results)} stores -> {output_csv}")
    else:
        # still write headers (useful)
        with open(output_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
        print("❌ No results (created empty output with headers).")

if __name__ == "__main__":
    run("brands.csv", "leads.csv")
