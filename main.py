import csv
import time
import re
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from dotenv import load_dotenv

# ============================================================
# ENV + GLOBALS
# ============================================================

load_dotenv(override=True)

from google_search import generate_brands_csv


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

PHONE_RE = re.compile(
    r"(?:(?:\+|00)\s?39\s?)?"
    r"(?:0\d{1,3}|\d{3,4})"
    r"[\s./-]?\d{2,4}"
    r"(?:[\s./-]?\d{2,4}){1,3}"
)

# P.IVA (11 digits) with optional IT prefix
VAT_RE = re.compile(r"\b(?:IT\s*)?(\d{11})\b", re.IGNORECASE)

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
# BASIC HELPERS (UPDATED: resolve myshopify -> real domain)
# ============================================================

def extract_domain(url: str):
    try:
        parsed = urlparse((url or "").strip())
        domain = (parsed.netloc or "").lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain or None
    except Exception:
        return None

def get_base_url(url: str) -> str:
    """
    Converts https://example.com/path -> https://example.com
    """
    p = urlparse((url or "").strip())
    if not p.scheme or not p.netloc:
        return (url or "").strip()
    return f"{p.scheme}://{p.netloc}"

def safe_get(url: str, timeout=15):
    """
    Return (Response, final_url) only if status_code == 200, else (None, final_url_or_original).
    Follows redirects.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        final_url = (r.url or url) if r is not None else url
        if r is not None and r.status_code == 200:
            return r, final_url
        return None, final_url
    except Exception:
        return None, url

def resolve_store_homepage_url(input_url: str, timeout: int = 15) -> str:
    """
    Given a URL from CSV (often *.myshopify.com), return the final redirected homepage base URL.
    Example: https://stuffboutiqueit.myshopify.com/ -> https://stuffboutique.it
    """
    u = (input_url or "").strip()
    if not u:
        return ""

    if not u.startswith(("http://", "https://")):
        u = "https://" + u

    r, final_url = safe_get(u, timeout=timeout)
    if final_url:
        return get_base_url(final_url)

    return get_base_url(u)

# ============================================================
# BRAND (TITLE TAG ONLY, as requested)
# ============================================================

def extract_brand_from_title(soup: BeautifulSoup, url: str = "") -> str:
    title_tag = soup.find("title")
    if not title_tag:
        return ""

    raw_title = title_tag.get_text(" ", strip=True)
    raw_title = re.sub(r"\s+", " ", raw_title).strip()

    parts = re.split(r"\s*[\|\-–•·:]\s*", raw_title)

    junk_words = [
        "shop", "store", "official", "online", "acquista", "buy",
        "spedizione", "free shipping", "sale", "sconto",
        "collezione", "collection", "scarpe", "uomo", "donna",
        "home", "homepage"
    ]

    candidates = []
    for part in parts:
        clean = part.strip()
        if len(clean) > 60 or len(clean) < 2:
            continue
        lower = clean.lower()
        if any(word in lower for word in junk_words):
            continue
        candidates.append(clean)

    if candidates:
        return min(candidates, key=len).strip()

    if parts:
        fallback = min(parts, key=len).strip()
        if 2 <= len(fallback) <= 60:
            return fallback

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
    """
    try:
        collections_url = urljoin(base_url, "/collections/all")
        r, _ = safe_get(collections_url, timeout=12)
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

def extract_contact_info(base_url: str, soup: BeautifulSoup, html: str, max_pages: int = 10, sleep_s: float = 0.6):
    emails, phones = set(), set()

    e1, p1 = _extract_mailto_tel(soup)
    e2, p2 = _extract_from_text(soup)
    e3, p3 = _extract_from_jsonld(soup)
    e4 = _extract_obfuscated_emails(html)

    emails |= (e1 | e2 | e3 | e4)
    phones |= (p1 | p2 | p3)

    pages = _discover_contactish_links(soup, base_url, limit=max_pages) + _candidate_shopify_paths(base_url)

    seen = set()
    unique_pages = []
    for p in pages:
        if p not in seen:
            seen.add(p)
            unique_pages.append(p)
    unique_pages = unique_pages[:max_pages]

    if (not emails) or (not phones):
        for purl in unique_pages:
            time.sleep(sleep_s)
            r, _ = safe_get(purl, timeout=12)
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
# P.IVA extraction (MAIN DOMAIN scan)
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

def extract_piva_from_domain(base_url: str, max_pages: int = 8, sleep_s: float = 0.4) -> str:
    """
    Scan homepage + a few internal legal/contact pages to find P.IVA.
    Returns first 11-digit P.IVA found, else "".
    """
    r, final_url = safe_get(base_url, timeout=15)
    if not r:
        return ""

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    vats = extract_vat_numbers(text)
    if vats:
        return vats[0]

    pages = _discover_contactish_links(soup, get_base_url(final_url), limit=max_pages) + _candidate_shopify_paths(get_base_url(final_url))

    seen = set()
    candidates = []
    for p in pages:
        try:
            if urlparse(p).netloc == urlparse(get_base_url(final_url)).netloc and p not in seen:
                seen.add(p)
                candidates.append(p)
        except Exception:
            continue

    candidates = candidates[:max_pages]

    for purl in candidates:
        time.sleep(sleep_s)
        rr, _ = safe_get(purl, timeout=15)
        if not rr:
            continue
        psoup = BeautifulSoup(rr.text, "html.parser")
        ptext = psoup.get_text(" ", strip=True)
        vats = extract_vat_numbers(ptext)
        if vats:
            return vats[0]

    return ""

def pmi_detected(text: str) -> str:
    if not text:
        return "N"
    return "Y" if LEGAL_STRUCT_RE.search(text) else "N"

# ============================================================
# SCORE (removed Size dependency)
# ============================================================

def calculate_score(sku: int, text_search: str, ux: str, pmi: str) -> int:
    score = 0
    if sku >= 200:
        score += 1
    if text_search == "Y":
        score += 1
    if ux == "Y":
        score += 1
    if pmi == "Y":
        score += 1
    return score

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

    # Resolve myshopify -> real domain homepage
    homepage = resolve_store_homepage_url(url)
    if not homepage:
        print(f"❌ Bad URL: {url}")
        return None

    r, final_url = safe_get(homepage, timeout=15)
    if not r:
        print(f"❌ Failed: {homepage}")
        return None

    html = r.text
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    base_url = get_base_url(final_url)

    brand = extract_brand_from_title(soup, url=base_url)
    sku = count_skus(base_url, soup)
    text_search = has_text_only_search(soup)
    ux = has_refined_ux(soup)

    email, phone = extract_contact_info(base_url, soup, html, max_pages=10, sleep_s=0.6)

    # NEW: Extract P.IVA from MAIN DOMAIN pages
    piva = extract_piva_from_domain(base_url, max_pages=8, sleep_s=0.4)

    # PMI detection from homepage text
    pmi = pmi_detected(page_text)

    score = calculate_score(sku, text_search, ux, pmi)
    priority = priority_from_score(score)

    return {
        "brand": brand,
        "main_domain": base_url,     # resolved domain
        "category": category.strip(),
        "sku": sku,
        "Text Only Search": text_search,
        "UX Designed": ux,
        "PMI": pmi,
        "P.IVA": piva,
        "Score 0-4": score,
        "Platform": "Shopify",
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

            if not url:
                continue

            # Resolve early to dedupe by REAL main domain
            homepage = resolve_store_homepage_url(url)
            domain = extract_domain(homepage) if homepage else extract_domain(url)

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
        "main_domain",
        "category",
        "sku",
        "Text Only Search",
        "UX Designed",
        "PMI",
        "P.IVA",
        "Score 0-4",
        "Platform",
        "Email",
        "Tel",
        "Priority",
    ]

    with open(output_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        if results:
            writer.writerows(results)

    if results:
        print(f"\n✅ Saved {len(results)} stores -> {output_csv}")
    else:
        print("❌ No results (created empty output with headers).")

if __name__ == "__main__":
    # Step 1: Generate fresh brands.csv from SERP
    generate_brands_csv("brands.csv")

    # Step 2: Process those brands into leads.csv
    run("brands.csv", "leads.csv")