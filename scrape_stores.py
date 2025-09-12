# === scrape_stores.py — VERSION v3.2 (Playwright + scroll + debug) ===
import os, re, csv, time, datetime, requests, yaml, random
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from utils import parse_qty, unit_price, slugify
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

OUT_DIR = "out"
DEBUG_DIR = os.path.join(OUT_DIR, "debug")
OFERTAS_FULL = os.path.join(OUT_DIR, "ofertas_full.csv")
PROD_PRIMARY = os.path.join(OUT_DIR, "produtos_primary.csv")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
REQ_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
    "Cache-Control": "no-cache",
}
DEBUG_HTML = os.environ.get("DEBUG_HTML","0") == "1"

def ensure_dirs():
    os.makedirs(OUT_DIR, exist_ok=True)
    if DEBUG_HTML:
        os.makedirs(DEBUG_DIR, exist_ok=True)

def http(url, tries=2):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, timeout=30, headers=REQ_HEADERS)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last = e
            time.sleep(1.2 + i*0.8)
    raise last

def auto_scroll(page, max_steps=20, step_px=1200, sleep_ms=400):
    last_h = 0
    for _ in range(max_steps):
        page.evaluate(f"window.scrollBy(0, {step_px});")
        time.sleep(sleep_ms/1000)
        h = page.evaluate("document.body.scrollHeight")
        if h == last_h:
            break
        last_h = h

def fetch_rendered_pages(url, wait_selector=None, scroll=False, next_selector=None, max_pages=3, timeout_ms=20000):
    """Renderiza com Chromium e pode paginar/scrollar; devolve lista de HTMLs."""
    htmls = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="fr-FR", viewport={"width":1280,"height":1600})
        page = ctx.new_page()
        page.goto(url, wait_until="load", timeout=timeout_ms)
        if wait_selector:
            try: page.wait_for_selector(wait_selector, timeout=timeout_ms)
            except PWTimeout: pass
        if scroll:
            auto_scroll(page)
        htmls.append(page.content())

        # paginação (clicar "next")
        if next_selector:
            for i in range(1, max_pages):
                try:
                    if not page.locator(next_selector).first.is_visible():
                        break
                    page.locator(next_selector).first.click()
                    page.wait_for_load_state("load", timeout=timeout_ms)
                    if wait_selector:
                        try: page.wait_for_selector(wait_selector, timeout=timeout_ms)
                        except PWTimeout: pass
                    if scroll:
                        auto_scroll(page)
                    htmls.append(page.content())
                except Exception:
                    break

        browser.close()
    return htmls

def load_config(path="stores.yml"):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("stores", [])

def text(el): return el.get_text(" ", strip=True) if el else ""

def get_sel(s, key): 
    val = s.get(key); 
    return val if val else ""

def parse_cards(html, sel, base_url):
    soup = BeautifulSoup(html or "", "html.parser")
    cards = soup.select(sel["card"]) if sel.get("card") else []
    out = []
    for c in cards:
        def sel_one(selector):
            if not selector: return None
            try: return c.select_one(selector)
            except Exception: return None
        def sel_attr_img(selector):
            el = sel_one(selector)
            if not el: return ""
            for attr in ("src","data-src","data-original"):
                if el.has_attr(attr): return urljoin(base_url, el.get(attr))
            return ""
        def sel_href(selector):
            el = sel_one(selector)
            if el and el.has_attr("href"): return urljoin(base_url, el["href"])
            return ""

        title_el = sel_one(get_sel(sel, "title"))
        name = text(title_el)
        if not name: continue
        brand = text(sel_one(get_sel(sel, "brand")))
        qty   = text(sel_one(get_sel(sel, "qty")))

        price_el = sel_one(get_sel(sel, "price"))
        price = None
        if price_el:
            raw = text(price_el)
            raw = raw.replace("\xa0"," ").replace(",",".")
            m = re.search(r"(\d+(?:\.\d+)?)", raw)
            if m:
                try: price = float(m.group(1))
                except ValueError: price = None

        promo = bool(sel_one(get_sel(sel, "promo")))
        url   = sel_href(get_sel(sel, "link"))
        img   = sel_attr_img(get_sel(sel, "image"))
        ean   = ""

        out.append({"name": name, "brand": brand, "qty": qty, "price": price,
                    "promo": promo, "url": url, "img": img, "ean": ean})
    return out

def main():
    print(">> Running scrape_stores.py VERSION v3.2")
    ensure_dirs()
    stores = load_config()

    ofertas_rows = []
    produtos_map = {}
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat()+"Z"

    for store in stores:
        code     = store.get("code", "STORE")
        name     = store.get("name", code)
        country  = store.get("country", "LU")
        base     = store.get("base_url", "")
        sel      = store.get("selectors", {})
        sources  = store.get("sources", [])

        for idx, src in enumerate(sources):
            stype  = src.get("type")
            url    = src.get("url")
            render = bool(src.get("render"))
            scroll = bool(src.get("scroll"))
            next_sel = src.get("next_selector")  # opcional
            max_pages = int(src.get("max_pages", 3))
            if not url or not stype: continue

            try:
                pages_html = []
                if stype == "pdf":
                    pages_html = []
                else:
                    wait_sel = sel.get("card")
                    if render:
                        pages_html = fetch_rendered_pages(url, wait_selector=wait_sel, scroll=scroll,
                                                          next_selector=next_sel, max_pages=max_pages)
                    else:
                        pages_html = [http(url)]
            except Exception as e:
                print(f"[{code}] erro ao abrir {url}: {e}")
                continue

            # debug: guardar HTML
            if DEBUG_HTML:
                for p_i, h in enumerate(pages_html):
                    path = os.path.join(DEBUG_DIR, f"{code}_{idx:02d}_{p_i:02d}.html")
                    try:
                        with open(path,"w",encoding="utf-8") as f: f.write(h)
                    except Exception: pass

            for html in pages_html:
                items = []
                if stype in ("category", "offers_page"):
                    items = parse_cards(html, sel, base)
                elif stype == "pdf":
                    items = []
                else:
                    continue

                for it in items:
                    uid = it["ean"] if it["ean"] else slugify(it["name"], it["brand"], it["qty"])
                    qv, baseu = parse_qty(it["qty"])
                    pu, unit  = unit_price(it["price"], qv, baseu)

                    ofertas_rows.append({
                        "ProductUID": uid,
                        "EAN": it["ean"],
                        "NomeProduto": it["name"],
                        "Loja": name,
                        "Store": code,
                        "Country": country,
                        "Preco": it["price"] if it["price"] is not None else "",
                        "Moeda": "EUR",
                        "PrecoUnidade": pu or "",
                        "Unidade": unit or "",
                        "IsPromo": "TRUE" if stype in ("offers_page","pdf") else ("TRUE" if it["promo"] else "FALSE"),
                        "ValidadeDe": "",
                        "ValidadeAte": "",
                        "SourceURL": it["url"],
                        "SourceType": "folheto" if stype in ("offers_page","pdf") else "categoria",
                        "FetchedAt": now
                    })

                    if uid not in produtos_map:
                        produtos_map[uid] = {
                            "UID": uid,
                            "EAN": it["ean"],
                            "Nome": it["name"],
                            "Marca": it["brand"],
                            "Rayon": "",
                            "SousRayon": "",
                            "Tamanho": it["qty"],
                            "Imagem": it["img"],
                            "Fonte": code,
                            "ScoreInicial": 5.0
                        }
            time.sleep(0.2 + random.random()*0.2)

    cols_o = ["ProductUID","EAN","NomeProduto","Loja","Store","Country","Preco","Moeda",
              "PrecoUnidade","Unidade","IsPromo","ValidadeDe","ValidadeAte",
              "SourceURL","SourceType","FetchedAt"]
    with open(OFERTAS_FULL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols_o); w.writeheader()
        for r in ofertas_rows: w.writerow(r)
    print(f"✅ ofertas_full.csv ({len(ofertas_rows)} linhas)")

    cols_p = ["UID","EAN","Nome","Marca","Rayon","SousRayon","Tamanho","Imagem","Fonte","ScoreInicial"]
    with open(PROD_PRIMARY, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols_p); w.writeheader()
        for r in produtos_map.values(): w.writerow(r)
    print(f"✅ produtos_primary.csv ({len(produtos_map)} itens)")

if __name__ == "__main__":
    main()
