import re, unicodedata

def parse_qty(text):
    if not text: return None, None
    t = text.lower().replace(",", ".")
    # ex: 6x200 ml, 2 x 500 g
    m = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(kg|g|l|ml)", t)
    if m:
        n1, n2, u = float(m.group(1)), float(m.group(2)), m.group(3)
        qty = n1 * n2
        base = "g" if u in ["kg","g"] else "ml"
        if u == "kg": qty *= 1000
        if u == "l":  qty *= 1000
        return qty, base
    # ex: 500 g, 1 kg, 1 L, 330 ml, 12 un
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|g|l|ml|un|unid|unit)", t)
    if m:
        n, u = float(m.group(1)), m.group(2)
        base = "g" if u in ["kg","g"] else ("ml" if u in ["l","ml"] else "un")
        if u == "kg": n *= 1000
        if u == "l":  n *= 1000
        return n, base
    return None, None

def unit_price(price, qty, base):
    if not price or not qty or not base: return None, None
    if base == "g":  return round(price/(qty/1000),4), "kg"
    if base == "ml": return round(price/(qty/1000),4), "L"
    return round(price/qty,4), "unid"

def slugify(*parts):
    s = " ".join([p for p in parts if p]).lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'[^a-z0-9]+','-', s).strip('-')
    return s
