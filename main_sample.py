import csv
import json
import re
import time
import html
from typing import List, Set, Tuple, Dict, Optional
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

from google_search import generate_brands_csv  # keep if you use it elsewhere


# ============================================================
# ENV + GLOBALS
# ============================================================

load_dotenv()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Connection": "keep-alive",
}

BAD_EMAIL_SUBSTRINGS = {
    "example.com",
    "sentry.io",
    "shopify.com",
    "wix.com",
    "wordpress.com",
    "webflow.com",
    "cloudflare.com",
    "google.com",
    "googletagmanager.com",
    "gstatic.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "pinterest.com",
    "youtube.com",
    "vimeo.com",
    "klaviyo.com",
    "mailchimp.com",
}

COMMON_GENERIC_EMAIL_PREFIXES = {
    "info",
    "hello",
    "ciao",
    "support",
    "assistenza",
    "contact",
    "contatti",
    "customer",
    "care",
    "admin",
    "office",
    "sales",
    "store",
    "shop",
}

PHONE_CONTEXT_KEYWORDS = [
    "tel", "telefono", "phone", "mobile", "cell", "whatsapp",
    "contatti", "contact", "assistenza", "supporto", "customer care"
]

CONTACT_LINK_KEYWORDS = [
    "contatti", "contatto", "contact", "contact-us", "contactus",
    "assistenza", "support", "supporto", "customer-service",
    "customer-care", "help", "help-center", "helpcentre",
    "chi-siamo", "about", "about-us", "company",
    "impressum", "legal", "note-legali", "privacy", "refund",
    "return", "returns", "shipping", "spedizioni", "faq", "where-we-are"
]

EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    re.IGNORECASE
)

# Good general-purpose phone regex for EU / Italy style numbers
PHONE_RE = re.compile(
    r"(?<!\w)"
    r"(?:(?:\+|00)\s?\d{1,3}[\s./-]?)?"
    r"(?:\(?\d{2,4}\)?[\s./-]?)?"
    r"\d{2,4}"
    r"(?:[\s./-]?\d{2,4}){2,4}"
    r"(?!\w)"
)

VAT_RE = re.compile(r"\b(?:IT\s*)?(\d{11})\b", re.IGNORECASE)

LEGAL_STRUCT_RE = re.compile(
    r"\b("
    r"s\.?\s*r\.?\s*l\.?|"
    r"s\.?\s*p\.?\s*a\.?|"
    r"s\.?\s*a\.?\s*s\.?|"
    r"s\.?\s*n\.?\s*c\.?|"
    r"unipersonale|"
    r"societ[aà]\s+cooperativa|"
    r"coop\.?|"
    r"ltd|limited|llc|inc\.?|incorporated|corp\.?|gmbh|pty"
    r")\b",
    re.IGNORECASE
)

SOCIAL_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "youtube.com",
    "pinterest.com",
}

WHATSAPP_RE = re.compile(
    r"(?:https?:\/\/)?(?:wa\.me\/|api\.whatsapp\.com\/send\?phone=)(\+?\d+)",
    re.IGNORECASE
)


# ============================================================
# SESSION / NETWORK
# ============================================================

def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(HEADERS)
    return session


SESSION = build_session()


def safe_get(url: str, timeout: int = 18) -> Tuple[Optional[requests.Response], str]:
    try:
        r = SESSION.get(url, timeout=timeout, allow_redirects=True)
        final_url = r.url if r is not None and r.url else url
        if r is not None and r.status_code == 200 and "text/html" in r.headers.get("Content-Type", ""):
            return r, final_url
        return None, final_url
    except Exception:
        return None, url


# ============================================================
# URL HELPERS
# ============================================================

def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def extract_domain(url: str) -> Optional[str]:
    try:
        parsed = urlparse(normalize_url(url))
        domain = (parsed.netloc or "").lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain or None
    except Exception:
        return None


def get_base_url(url: str) -> str:
    try:
        p = urlparse(normalize_url(url))
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
        return normalize_url(url)
    except Exception:
        return normalize_url(url)


def same_domain(url1: str, url2: str) -> bool:
    d1 = extract_domain(url1)
    d2 = extract_domain(url2)
    return bool(d1 and d2 and d1 == d2)


def resolve_store_homepage_url(input_url: str, timeout: int = 18) -> str:
    u = normalize_url(input_url)
    if not u:
        return ""
    r, final_url = safe_get(u, timeout=timeout)
    if final_url:
        return get_base_url(final_url)
    return get_base_url(u)


# ============================================================
# NORMALIZATION HELPERS
# ============================================================

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def digits_only(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def normalize_email(email: str) -> str:
    email = clean_text(email).lower()
    email = email.strip(".,;:<>[](){}\"' ")
    return email


def is_valid_email(email: str) -> bool:
    email = normalize_email(email)
    if not email or not EMAIL_RE.fullmatch(email):
        return False
    if any(bad in email for bad in BAD_EMAIL_SUBSTRINGS):
        return False
    return True


def normalize_phone(raw: str) -> str:
    p = clean_text(raw)
    p = p.replace("\u00a0", " ")
    p = re.sub(r"[^\d+()./\-\s]", "", p)
    p = re.sub(r"\s+", " ", p).strip(" .,:;")
    return p


def canonical_phone(raw: str) -> str:
    p = normalize_phone(raw)
    digits = digits_only(p)

    if not digits:
        return ""

    # Convert 0039... to +39...
    if digits.startswith("0039"):
        return "+39" + digits[4:]

    # Already likely international
    if p.startswith("+"):
        return "+" + digits

    # Italian numbers often start with 0 landline or 3 mobile
    if digits.startswith("39") and len(digits) >= 10:
        return "+" + digits

    if len(digits) >= 8:
        return digits

    return ""


def is_valid_phone(raw: str) -> bool:
    c = canonical_phone(raw)
    digits = digits_only(c)
    if len(digits) < 8 or len(digits) > 15:
        return False

    # Reject obvious junk
    if len(set(digits)) == 1:
        return False
    if digits.startswith("0000"):
        return False
    return True


# ============================================================
# JSON-LD HELPERS
# ============================================================

def iter_jsonld_objects(soup: BeautifulSoup):
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts:
        raw = script.string or script.get_text(strip=True) or ""
        raw = raw.strip()
        if not raw:
            continue

        try:
            data = json.loads(raw)
            yield data
        except Exception:
            # Some sites include malformed JSON-LD; ignore safely
            continue


def walk_json(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_json(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_json(item)


# ============================================================
# BRAND EXTRACTION
# ============================================================

def extract_brand_from_title(soup: BeautifulSoup, url: str = "") -> str:
    title_tag = soup.find("title")
    if not title_tag:
        domain = extract_domain(url or "")
        return domain.split(".")[0].title() if domain else ""

    raw_title = clean_text(title_tag.get_text(" ", strip=True))
    parts = re.split(r"\s*[\|\-–•·:]\s*", raw_title)

    junk_words = [
        "shop", "store", "official", "online", "acquista", "buy",
        "spedizione", "free shipping", "sale", "sconto", "collezione",
        "collection", "scarpe", "uomo", "donna", "home", "homepage",
        "pagina", "page", "welcome"
    ]

    candidates = []
    for part in parts:
        part = clean_text(part)
        lower = part.lower()
        if not (2 <= len(part) <= 60):
            continue
        if any(word in lower for word in junk_words):
            continue
        candidates.append(part)

    if candidates:
        return min(candidates, key=len)

    domain = extract_domain(url or "")
    return domain.split(".")[0].title() if domain else raw_title[:60]


def extract_brand_from_jsonld(soup: BeautifulSoup) -> str:
    for obj in iter_jsonld_objects(soup):
        for item in walk_json(obj):
            if not isinstance(item, dict):
                continue
            t = str(item.get("@type", "")).lower()
            if t in {"organization", "brand", "store", "localbusiness", "corporation"}:
                name = clean_text(str(item.get("name", "")))
                if 2 <= len(name) <= 100:
                    return name
    return ""


def extract_brand(soup: BeautifulSoup, url: str = "") -> str:
    brand = extract_brand_from_jsonld(soup)
    if brand:
        return brand
    return extract_brand_from_title(soup, url=url)


# ============================================================
# PLATFORM DETECTION
# ============================================================

def detect_platform(html_text: str, soup: BeautifulSoup) -> str:
    lower_html = html_text.lower()

    shopify_signals = [
        "cdn.shopify.com",
        "myshopify.com",
        "shopify.theme",
        "shopify-payment-button",
        "/products/",
        "/collections/",
        "shopify-section",
    ]
    if any(sig in lower_html for sig in shopify_signals):
        return "Shopify"

    woocommerce_signals = [
        "woocommerce",
        "wp-content/plugins/woocommerce",
        "add_to_cart_button",
    ]
    if any(sig in lower_html for sig in woocommerce_signals):
        return "WooCommerce"

    return "Unknown"


# ============================================================
# SKU COUNT
# ============================================================

def count_skus(base_url: str, homepage_soup: BeautifulSoup) -> int:
    selectors = [
        'a[href*="/products/"]',
        ".product-item",
        ".product-card",
        ".grid-product",
        ".card-product",
        "[data-product-id]",
        "[data-product-handle]",
    ]

    # First try collections/all for Shopify-like stores
    collections_url = urljoin(base_url, "/collections/all")
    r, _ = safe_get(collections_url, timeout=12)
    if r:
        coll_soup = BeautifulSoup(r.text, "html.parser")
        best = 0
        for sel in selectors:
            best = max(best, len(coll_soup.select(sel)))
        if best > 0:
            return min(best * 3, 1000)

    # Fallback on homepage
    best = 0
    for sel in selectors:
        best = max(best, len(homepage_soup.select(sel)))

    if best > 0:
        return min(best, 500)

    links = homepage_soup.find_all("a", href=re.compile(r"/products?/", re.I))
    return min(len(links), 500)


# ============================================================
# UX / SEARCH
# ============================================================

def has_text_only_search(soup: BeautifulSoup) -> str:
    search_inputs = (
        soup.find("input", {"type": "search"}) or
        soup.find("input", {"name": re.compile(r"q|search|query", re.I)}) or
        soup.find("input", {"placeholder": re.compile(r"search|cerca|find", re.I)}) or
        soup.find("input", {"id": re.compile(r"search|query", re.I)})
    )

    text = soup.get_text(" ", strip=True).lower()
    search_words = ["search", "cerca", "ricerca", "trova"]
    ecommerce_words = [
        "/products/", "add to cart", "aggiungi al carrello",
        "price", "prezzo", "buy now", "acquista", "collezione"
    ]

    has_search = bool(search_inputs) or any(w in text for w in search_words)
    has_products = any(w in text for w in ecommerce_words)
    return "Y" if has_search and has_products else "N"


def has_refined_ux(soup: BeautifulSoup) -> str:
    checks = 0

    if soup.find(["nav", "header"]):
        checks += 1
    if soup.find("footer"):
        checks += 1
    if soup.find_all(["section", "div"], class_=re.compile(r"product|grid|collection|catalog", re.I)):
        checks += 1

    nav = soup.find("nav") or soup.find("ul", class_=re.compile(r"menu|nav", re.I))
    if nav and len(nav.find_all("a")) > 3:
        checks += 1

    if soup.find("input", {"type": "search"}) or soup.find(attrs={"aria-label": re.compile(r"search|cerca", re.I)}):
        checks += 1

    return "Y" if checks >= 2 else "N"


# ============================================================
# CONTACT PAGE DISCOVERY
# ============================================================

def discover_contactish_links(soup: BeautifulSoup, base_url: str, limit: int = 12) -> List[str]:
    links = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = clean_text(a.get("href", ""))
        text = clean_text(a.get_text(" ", strip=True)).lower()
        blob = f"{href} {text}".lower()

        if any(keyword in blob for keyword in CONTACT_LINK_KEYWORDS):
            full = urljoin(base_url, href)
            if same_domain(full, base_url) and full not in seen:
                seen.add(full)
                links.append(full)

        if len(links) >= limit:
            break

    return links


def candidate_shopify_paths(base_url: str) -> List[str]:
    paths = [
        "/pages/contact",
        "/pages/contact-us",
        "/pages/contatti",
        "/pages/contatto",
        "/pages/contattaci",
        "/pages/assistenza",
        "/pages/supporto",
        "/pages/customer-care",
        "/pages/servizio-clienti",
        "/pages/about",
        "/pages/about-us",
        "/pages/chi-siamo",
        "/policies/privacy-policy",
        "/policies/terms-of-service",
        "/policies/refund-policy",
        "/policies/shipping-policy",
    ]
    return [urljoin(base_url, p) for p in paths]


# ============================================================
# EMAIL EXTRACTION
# ============================================================

def extract_emails_from_mailto(soup: BeautifulSoup) -> Set[str]:
    emails = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            email = href.split(":", 1)[1].split("?", 1)[0].strip()
            email = normalize_email(email)
            if is_valid_email(email):
                emails.add(email)
    return emails


def extract_emails_from_text(text: str) -> Set[str]:
    emails = set()
    for email in EMAIL_RE.findall(text or ""):
        email = normalize_email(email)
        if is_valid_email(email):
            emails.add(email)
    return emails


def extract_obfuscated_emails(text: str) -> Set[str]:
    found = set()

    patterns = [
        r"([A-Za-z0-9._%+-]+)\s*(?:@|\(at\)|\[at\]|\sat\s)\s*([A-Za-z0-9.-]+)\s*(?:\.|\(dot\)|\[dot\]|\sdot\s)\s*([A-Za-z]{2,})",
    ]

    for pat in patterns:
        for m in re.findall(pat, text, flags=re.IGNORECASE):
            email = f"{m[0]}@{m[1]}.{m[2]}"
            email = normalize_email(email)
            if is_valid_email(email):
                found.add(email)

    return found


def extract_emails_from_jsonld(soup: BeautifulSoup) -> Set[str]:
    emails = set()
    for obj in iter_jsonld_objects(soup):
        for node in walk_json(obj):
            if isinstance(node, dict):
                for key in ("email",):
                    value = node.get(key)
                    if isinstance(value, str):
                        email = normalize_email(value.replace("mailto:", ""))
                        if is_valid_email(email):
                            emails.add(email)
    return emails


# ============================================================
# PHONE EXTRACTION
# ============================================================

def extract_phones_from_tel(soup: BeautifulSoup) -> Set[str]:
    phones = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()

        if href.lower().startswith("tel:"):
            phone = href.split(":", 1)[1].split("?", 1)[0].strip()
            if is_valid_phone(phone):
                phones.add(canonical_phone(phone))

        m = WHATSAPP_RE.search(href)
        if m:
            phone = m.group(1)
            if is_valid_phone(phone):
                phones.add(canonical_phone(phone))

    return phones


def extract_phones_from_text(text: str) -> Set[str]:
    phones = set()
    if not text:
        return phones

    for match in PHONE_RE.findall(text):
        if is_valid_phone(match):
            phones.add(canonical_phone(match))
    return phones


def extract_phones_from_jsonld(soup: BeautifulSoup) -> Set[str]:
    phones = set()
    for obj in iter_jsonld_objects(soup):
        for node in walk_json(obj):
            if not isinstance(node, dict):
                continue

            for key in ("telephone", "phone"):
                value = node.get(key)
                if isinstance(value, str) and is_valid_phone(value):
                    phones.add(canonical_phone(value))

            contact_point = node.get("contactPoint")
            if isinstance(contact_point, dict):
                tel = contact_point.get("telephone")
                if isinstance(tel, str) and is_valid_phone(tel):
                    phones.add(canonical_phone(tel))
            elif isinstance(contact_point, list):
                for cp in contact_point:
                    if isinstance(cp, dict):
                        tel = cp.get("telephone")
                        if isinstance(tel, str) and is_valid_phone(tel):
                            phones.add(canonical_phone(tel))
    return phones


def extract_phone_candidates_near_keywords(soup: BeautifulSoup) -> Set[str]:
    phones = set()

    for tag in soup.find_all(["p", "div", "span", "li", "address", "footer"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        low = txt.lower()
        if any(k in low for k in PHONE_CONTEXT_KEYWORDS):
            for match in PHONE_RE.findall(txt):
                if is_valid_phone(match):
                    phones.add(canonical_phone(match))

    return phones


# ============================================================
# VAT / PMI / SOCIAL
# ============================================================

def extract_vat_numbers(text: str) -> List[str]:
    if not text:
        return []
    vats = VAT_RE.findall(text)
    out = []
    seen = set()
    for vat in vats:
        vat = vat.strip()
        if len(vat) == 11 and vat not in seen:
            seen.add(vat)
            out.append(vat)
    return out


def pmi_detected(text: str) -> str:
    if not text:
        return "N"
    return "Y" if LEGAL_STRUCT_RE.search(text) else "N"


def extract_social_links(soup: BeautifulSoup, base_url: str) -> Dict[str, str]:
    socials = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"].strip())
        domain = extract_domain(href) or ""
        for social_domain in SOCIAL_DOMAINS:
            if social_domain in domain:
                socials[social_domain] = href
    return socials


# ============================================================
# CONTACT PRIORITIZATION
# ============================================================

def score_email(email: str, website_domain: str) -> Tuple[int, str]:
    email = normalize_email(email)
    local = email.split("@")[0] if "@" in email else ""
    domain = email.split("@")[1] if "@" in email else ""

    score = 0

    if website_domain and domain == website_domain:
        score += 5
    elif website_domain and website_domain in domain:
        score += 4

    if local in COMMON_GENERIC_EMAIL_PREFIXES:
        score += 2

    if "noreply" in local or "no-reply" in local:
        score -= 10

    return score, email


def select_best_email(emails: Set[str], website_domain: str) -> str:
    valid = [e for e in emails if is_valid_email(e)]
    if not valid:
        return ""
    ranked = sorted((score_email(e, website_domain) for e in valid), reverse=True)
    return ranked[0][1]


def score_phone(phone: str, page_url: str = "") -> Tuple[int, str]:
    score = 0
    digits = digits_only(phone)

    if phone.startswith("+39") or digits.startswith("39"):
        score += 4
    elif digits.startswith("0") or digits.startswith("3"):
        score += 3

    if 8 <= len(digits) <= 15:
        score += 2

    return score, phone


def select_best_phone(phones: Set[str]) -> str:
    valid = [p for p in phones if is_valid_phone(p)]
    if not valid:
        return ""
    ranked = sorted((score_phone(p) for p in valid), reverse=True)
    return ranked[0][1]


# ============================================================
# PAGE-LEVEL EXTRACTION
# ============================================================

def extract_page_contacts(soup: BeautifulSoup, html_text: str) -> Tuple[Set[str], Set[str]]:
    emails = set()
    phones = set()

    page_text = clean_text(soup.get_text(" ", strip=True))

    emails |= extract_emails_from_mailto(soup)
    emails |= extract_emails_from_text(page_text)
    emails |= extract_emails_from_jsonld(soup)
    emails |= extract_obfuscated_emails(html_text)

    phones |= extract_phones_from_tel(soup)
    phones |= extract_phones_from_text(page_text)
    phones |= extract_phones_from_jsonld(soup)
    phones |= extract_phone_candidates_near_keywords(soup)

    return emails, phones


def extract_contact_info(base_url: str, soup: BeautifulSoup, html_text: str,
                         max_pages: int = 10, sleep_s: float = 0.5) -> Tuple[str, str]:
    all_emails = set()
    all_phones = set()

    website_domain = extract_domain(base_url) or ""

    e, p = extract_page_contacts(soup, html_text)
    all_emails |= e
    all_phones |= p

    pages = discover_contactish_links(soup, base_url, limit=max_pages)
    pages += candidate_shopify_paths(base_url)

    unique_pages = []
    seen = set()
    for purl in pages:
        if purl not in seen and same_domain(purl, base_url):
            seen.add(purl)
            unique_pages.append(purl)

    unique_pages = unique_pages[:max_pages]

    for purl in unique_pages:
        if all_emails and all_phones:
            break

        time.sleep(sleep_s)
        r, _ = safe_get(purl, timeout=15)
        if not r:
            continue

        csoup = BeautifulSoup(r.text, "html.parser")
        e2, p2 = extract_page_contacts(csoup, r.text)
        all_emails |= e2
        all_phones |= p2

    email = select_best_email(all_emails, website_domain=website_domain)
    phone = select_best_phone(all_phones)
    return email, phone


# ============================================================
# VAT EXTRACTION ACROSS DOMAIN
# ============================================================

def extract_piva_from_domain(base_url: str, max_pages: int = 8, sleep_s: float = 0.4) -> str:
    r, final_url = safe_get(base_url, timeout=15)
    if not r:
        return ""

    resolved_base = get_base_url(final_url)
    soup = BeautifulSoup(r.text, "html.parser")
    texts_to_scan = [
        clean_text(soup.get_text(" ", strip=True)),
        r.text,
    ]

    for txt in texts_to_scan:
        vats = extract_vat_numbers(txt)
        if vats:
            return vats[0]

    pages = discover_contactish_links(soup, resolved_base, limit=max_pages)
    pages += candidate_shopify_paths(resolved_base)

    unique_pages = []
    seen = set()
    for purl in pages:
        if purl not in seen and same_domain(purl, resolved_base):
            seen.add(purl)
            unique_pages.append(purl)

    unique_pages = unique_pages[:max_pages]

    for purl in unique_pages:
        time.sleep(sleep_s)
        rr, _ = safe_get(purl, timeout=15)
        if not rr:
            continue

        texts_to_scan = [rr.text]
        psoup = BeautifulSoup(rr.text, "html.parser")
        texts_to_scan.append(clean_text(psoup.get_text(" ", strip=True)))

        for txt in texts_to_scan:
            vats = extract_vat_numbers(txt)
            if vats:
                return vats[0]

    return ""


# ============================================================
# SCORE
# ============================================================

def calculate_score(sku: int, text_search: str, ux: str, pmi: str,
                    email: str, phone: str, piva: str) -> int:
    score = 0

    if sku >= 200:
        score += 1
    if text_search == "Y":
        score += 1
    if ux == "Y":
        score += 1
    if pmi == "Y":
        score += 1
    if email:
        score += 1
    if phone:
        score += 1
    if piva:
        score += 1

    return score


def priority_from_score(score: int) -> str:
    if score >= 6:
        return "HIGH"
    if score >= 4:
        return "MEDIUM"
    return "LOW"


# ============================================================
# MAIN EXTRACTION
# ============================================================

def process_store(url: str, category: str) -> Optional[Dict[str, str]]:
    print(f"Processing: {url}")

    homepage = resolve_store_homepage_url(url)
    if not homepage:
        print(f"Failed to normalize URL: {url}")
        return None

    r, final_url = safe_get(homepage, timeout=18)
    if not r:
        print(f"Failed to fetch: {homepage}")
        return None

    html_text = r.text
    soup = BeautifulSoup(html_text, "html.parser")
    base_url = get_base_url(final_url)
    page_text = clean_text(soup.get_text(" ", strip=True))

    brand = extract_brand(soup, url=base_url)
    platform = detect_platform(html_text, soup)
    sku = count_skus(base_url, soup)
    text_search = has_text_only_search(soup)
    ux = has_refined_ux(soup)
    email, phone = extract_contact_info(base_url, soup, html_text, max_pages=10, sleep_s=0.5)
    piva = extract_piva_from_domain(base_url, max_pages=8, sleep_s=0.4)
    pmi = pmi_detected(page_text)

    socials = extract_social_links(soup, base_url)
    instagram = socials.get("instagram.com", "")
    linkedin = socials.get("linkedin.com", "")
    facebook = socials.get("facebook.com", "")

    score = calculate_score(
        sku=sku,
        text_search=text_search,
        ux=ux,
        pmi=pmi,
        email=email,
        phone=phone,
        piva=piva
    )
    priority = priority_from_score(score)

    return {
        "brand": brand,
        "main_domain": base_url,
        "category": category.strip(),
        "sku": sku,
        "Text Only Search": text_search,
        "UX Designed": ux,
        "PMI": pmi,
        "P.IVA": piva,
        "Score 0-7": score,
        "Platform": platform,
        "Email": email,
        "Tel": phone,
        "Instagram": instagram,
        "LinkedIn": linkedin,
        "Facebook": facebook,
        "Priority": priority,
    }


# ============================================================
# BATCH
# ============================================================

def run(input_csv: str, output_csv: str = "leads.csv", sleep_s: float = 1.2):
    seen_domains = set()
    results = []

    with open(input_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("Input CSV has no headers.")

        url_col = next((c for c in reader.fieldnames if "url" in c.lower()), None)
        cat_col = next((c for c in reader.fieldnames if "category" in c.lower() or "cat" in c.lower()), None)

    if not url_col:
        raise ValueError("Need a URL column containing 'url' in the header.")

    with open(input_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_url = (row.get(url_col) or "").strip()
            category = (row.get(cat_col) or "unknown").strip() if cat_col else "unknown"

            if not raw_url:
                continue

            resolved = resolve_store_homepage_url(raw_url)
            domain = extract_domain(resolved) or extract_domain(raw_url)

            if domain and domain in seen_domains:
                continue
            if domain:
                seen_domains.add(domain)

            result = process_store(raw_url, category)
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
        "Score 0-7",
        "Platform",
        "Email",
        "Tel",
        "Instagram",
        "LinkedIn",
        "Facebook",
        "Priority",
    ]

    with open(output_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        if results:
            writer.writerows(results)

    print(f"Saved {len(results)} rows to {output_csv}")


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    run("brands.csv", "leads.csv")