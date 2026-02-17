# B2B Leads Generation

A simple Python tool that uses **SerpApi (free credits)** to find Shopify-connected ecommerce brands and then analyzes each store to generate structured lead data, including SKU estimates, UX/search signals, platform detection, contact information, a score (0–5), and a priority level.

---

## FEATURES

- Uses your own `brands.csv` file  
- Extracts brand name from `<title>`  
- Estimates total products (SKU)  
- Detects search capability and UX quality  
- Classifies SME size (SMALL / MEDIUM / BIG)  
- Detects platform (Shopify / WooCommerce)  
- Extracts public email and phone number  
- Calculates a 0–5 score  
- Assigns PRIORITY (LOW / HIGH)  
- Exports results to CSV  

---

## OUTPUT COLUMNS

| Column | Description |
|--------|------------|
| Brand | Store name |
| URL | Website |
| Category | From queries |
| SKU | Estimated product count |
| Visual Search | Y / N |
| Text Only Search (Y/N) | Y / N |
| UX Designed (Y/N) | Y / N |
| Estimated SME | SMALL / MEDIUM / BIG |
| Score (0-5) | Lead score |
| Platform | Shopify / WooCommerce |
| Email | Public email if found |
| Phone Number | Public phone if found |
| PRIORITY | LOW (≤2) or HIGH (3–5) |

---

## SCORE (0–5)

- +1: Visual Search = Y  
- +1: SKU ≥ 100  
- +1: Text Search = Y  
- +1: UX Designed = Y  
- +1: SME = BIG  

**Maximum score: 5**

---

## PRIORITY RULE

- **LOW** → Score ≤ 2  
- **HIGH** → Score 3–5  

---

## NOTES

- Only publicly available information is collected.  
- SKU counts are estimates.  
- Contact fields may be empty if the store does not publish them.  
- Some stores may block automated requests.  
- Rate limiting is applied between requests.  
