import csv
import time
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

# ============================================================
# HELPERS
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Italy-leaning phone regex (+39 / 00 39 / Italian landline/mobile patterns)
PHONE_RE = re.compile(
    r"(?:(?:\+|00)\s?39\s?)?"
    r"(?:0\d{1,3}|\d{3,4})"
    r"[\s./-]?\d{2,4}"
    r"(?:[\s./-]?\d{2,4}){1,3}"
)

def extract_domain(url: str):
    """Extract clean domain from URL."""
    try:
        parsed = urlparse(url.strip())
        domain = (parsed.netloc or "").lower().replace("www.", "")
        return domain or None
    except:
        return None

def safe_get(url: str, timeout=15):
    """Safe HTTP request with timeout."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        return r
    except:
        return None

def extract_brand_from_title(soup: BeautifulSoup, url: str) -> str:
    """Get brand primarily from <title> tag."""
    title = soup.find("title")
    if title:
        brand = title.get_text().strip()
        brand = re.sub(r"\s*[\|\-–]\s*.*$", "", brand)
        if brand and 3 < len(brand) < 50:
            return brand[:50]

    og_site = soup.find("meta", property="og:site_name")
    if og_site and og_site.get("content"):
        return og_site.get("content").strip()[:50]

    domain = extract_domain(url)
    if domain:
        return domain.split(".")[0].replace("-", " ").title()
    return "Unknown Brand"

def count_skus(base_url: str, soup: BeautifulSoup) -> int:
    """Count total SKUs from collections page."""
    try:
        collections_url = urljoin(base_url, "/collections/all")
        r = safe_get(collections_url, timeout=12)
        if r and r.status_code == 200:
            coll_soup = BeautifulSoup(r.text, "html.parser")
            product_selectors = [
                'a[href*="/products/"]', 'a[href*="/product/"]',
                ".product-item", ".product-card", ".grid-item", "[data-product-id]"
            ]
            max_count = 0
            for selector in product_selectors:
                count = len(coll_soup.select(selector))
                max_count = max(max_count, count)

            # crude multiplier for pagination; capped
            return min(max_count * 3, 1000)

        product_links = soup.find_all("a", href=re.compile(r"/products?/"))
        return min(len(product_links), 500)
    except:
        pass
    return 10

def has_visual_search(soup: BeautifulSoup) -> str:
    """Check if site has product images."""
    img_selectors = [
        'img[src*="/products/"]', 'img[data-product]',
        ".product-image img", "[class*='product'] img",
        'img[alt*="product"]'
    ]
    for selector in img_selectors:
        if soup.select_one(selector):
            return "YES"
    return "NO" if len(soup.find_all("img")) == 0 else "YES"

def has_text_only_search(soup: BeautifulSoup) -> str:
    """Detect search functionality properly."""
    search_inputs = (
        soup.find("input", {"type": "search"}) or
        soup.find("input", {"name": re.compile(r"q|search|query", re.I)}) or
        soup.find("input", {"placeholder": re.compile(r"search|cerca|find", re.I)}) or
        soup.find("input", {"id": re.compile(r"search|query", re.I)})
    )

    all_text = soup.get_text().lower()
    search_texts = ["search", "cerca", "ricerca", "trova", "query", "q="]

    ecommerce_indicators = [
        "/products/", "product-title", "add to cart", "aggiungi al carrello",
        "price", "prezzo", "buy now", "acquista"
    ]

    has_search = bool(search_inputs) or any(text in all_text for text in search_texts)
    has_products = any(ind in all_text for ind in ecommerce_indicators)

    return "Y" if has_search and has_products else "N"

def has_refined_ux(soup: BeautifulSoup) -> str:
    """Check for refined/professional UX."""
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

def estimate_sme_scale(sku_count: int) -> str:
    """SME scale based on product count only."""
    if sku_count > 500:
        return "BIG"
    elif sku_count >= 100:
        return "MEDIUM"
    else:
        return "SMALL"

# ============================================================
# NEW CONTACT LOGIC (REPLACES OLD)
# ============================================================

def _normalize_phone(p: str) -> str:
    p = re.sub(r"\s+", " ", p).strip()
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

def _discover_contactish_links(soup: BeautifulSoup, base_url: str, limit=15):
    keywords = [
        "contatti", "contatto", "contact", "assistenza", "supporto",
        "customer", "servizio", "help", "resi", "res", "sped", "shipping",
        "privacy", "termini", "condizioni", "impressum", "chi-siamo", "about",
        "lavora", "azienda", "negozio", "dove", "store", "sede"
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
            except:
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
        "/pages/customer-care",
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
    """
    Strong extraction:
    - homepage: mailto/tel, text, jsonld, obfuscations
    - visit contact-ish links + common Shopify paths
    Returns: (email, phone)
    """
    emails, phones = set(), set()

    # Home extraction first
    e1, p1 = _extract_mailto_tel(soup)
    e2, p2 = _extract_from_text(soup)
    e3, p3 = _extract_from_jsonld(soup)
    e4 = _extract_obfuscated_emails(html)

    emails |= (e1 | e2 | e3 | e4)
    phones |= (p1 | p2 | p3)

    # Build list of pages to visit
    base_url = url
    pages = []
    pages += _discover_contactish_links(soup, base_url, limit=max_pages)
    pages += _candidate_shopify_paths(base_url)

    # de-dupe + cap
    seen = set()
    unique_pages = []
    for p in pages:
        if p not in seen:
            seen.add(p)
            unique_pages.append(p)
    unique_pages = unique_pages[:max_pages]

    # crawl extra pages if needed
    if (not emails) or (not phones):
        for purl in unique_pages:
            time.sleep(sleep_s)
            r = safe_get(purl, timeout=12)
            if not r or r.status_code != 200:
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
# PLATFORM + SCORE
# ============================================================

def get_platform(html: str, url: str) -> str:
    """Detect platform."""
    indicators = {
        "Shopify": ["cdn.shopify.com", "myshopify.com", "shopify.theme", "/cdn/shop/"],
        "WooCommerce": ["woocommerce", "wp-content/plugins/woocommerce"]
    }
    html_lower = html.lower()

    for platform, signs in indicators.items():
        if any(sign in html_lower for sign in signs):
            return platform
    # fallback (your request: mostly Shopify)
    return "Shopify"

def calculate_score(visual: str, sku: int, text_search: str, ux: str, sme: str) -> int:
    """Exact 0-5 scoring."""
    score = 0
    if visual == "YES": score += 1
    if sku >= 100: score += 1
    if text_search == "Y": score += 1
    if ux == "Y": score += 1
    if sme == "BIG": score += 1
    return min(score, 5)

def priority_from_score(score: int) -> str:
    return "LOW" if score <= 3 else "HIGH"

# ============================================================
# MAIN EXTRACTION
# ============================================================

def process_store(url: str, category: str):
    """Process single store."""
    print(f"🔍 Processing: {url}")

    r = safe_get(url, timeout=15)
    if not r or r.status_code != 200:
        print(f"❌ Failed: {url}")
        return None

    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    brand = extract_brand_from_title(soup, url)
    sku = count_skus(url, soup)
    visual_search = has_visual_search(soup)
    text_search = has_text_only_search(soup)
    ux = has_refined_ux(soup)
    sme_scale = estimate_sme_scale(sku)
    platform = get_platform(html, url)

    # ✅ NEW: stronger email/phone extraction
    email, phone = extract_contact_info(url, soup, html, max_pages=10, sleep_s=0.6)

    score = calculate_score(visual_search, sku, text_search, ux, sme_scale)
    priority = priority_from_score(score)

    return {
        "Brand": brand,
        "URL": url,
        "Category": category.strip(),
        "SKU": sku,
        "Visual Search": visual_search,
        "Text Only Search (Y/N)": text_search,
        "UX Designed (Y/N)": ux,
        "Estimated SME": sme_scale,
        "Score (0-5)": score,
        "Platform": platform,
        "Email": email,
        "Phone Number": phone,
        "PRIORITY": priority
    }

# ============================================================
# BATCH PROCESSOR
# ============================================================

def run(input_csv: str, output_csv: str = "store_analysis.csv", sleep_s: float = 1.5):
    """Process input CSV."""
    seen_domains = set()
    results = []

    # detect columns
    with open(input_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        url_col = next((col for col in reader.fieldnames if "url" in col.lower()), None)
        cat_col = next((col for col in reader.fieldnames if "category" in col.lower() or "cat" in col.lower()), None)

    if not url_col:
        raise ValueError("Need 'URL' or 'url' column")

    with open(input_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get(url_col, "").strip()
            category = row.get(cat_col, "unknown").strip() if cat_col else "unknown"

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

    if results:
        with open(output_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)

        print(f"\n Saved {len(results)} stores -> {output_csv}")
    else:
        print("❌ No results.")

if __name__ == "__main__":
    run("brands.csv", "leads.csv")
