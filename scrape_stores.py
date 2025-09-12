# === scrape_stores.py — VERSION v4.0 (render + folder/next + OCR folheto) ===
import os, re, csv, time, datetime, requests, yaml, random, io
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from utils import parse_qty, unit_price, slugify
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from PIL import Image
import pytesseract

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

def http_bytes(url):
    r = requests.get(url, timeout=30, headers=REQ_HEADERS)
    r.raise_for_status()
    return r.content

def auto_scroll(page, max_steps=24, step_px=1400, sleep_ms=350):
    last_h = 0
    for _ in range(max_steps):
        page.evaluate(f"window.scrollBy(0, {step_px});")
        time.sleep(sleep_ms/1000)
        h = page.evaluate("document.body.scrollHeight")
        if h == last_h:
            break
        last_h = h

def try_accept_cookies(page):
    texts = ["Accepter", "J'accepte", "Accept", "OK", "Accept all", "Tout accepter"]
    for t in texts:
        try:
            btn = page.get_by_text(t, exact=False).first
            if btn and btn.is_visible():
                btn.click(timeout=1500)
                time.sleep(0.4)
                return True
        except Exception:
            pass
    sels = [
        "[id*='cookie'] button", "[class*='cookie'] button",
        "button[aria-label*='cookie']", "button[aria-label*='consent']",
        "button:has-text('Accept')", "button:has-text(\"J'accepte\")"
    ]
    for s in sels:
        try:
            if page.locator(s).first.is_visible():
                page.locator(s).first.click(timeout=1500)
                time.sleep(0.4)
                return True
        except Exception:
            pass
    return False

def fetch_rendered_pages(url, wait_selector=None, scroll=False, next_selector=None, max_pages=3, timeout_ms=32000, open_first_folder=False, folder_card_selector="a[href]"):
    htmls = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="fr-FR", viewport={"width":1280,"height":1600})
        page = ctx.new_page()
        page.goto(url, wait_until="load", timeout=timeout_ms)
        try_accept_cookies(page)
        if open_first_folder:
            try:
                # abre o primeiro folder visível (Lidl)
                page.wait_for_selector(folder_card_selector, timeout=timeout_ms)
                page.locator(folder_card_selector).first.click()
                page.wait_for_load_state("load", timeout=timeout_ms)
                try_accept_cookies(page)
            except Exception:
                pass
        if wait_selector:
            try: page.wait_for_selector(wait_selector, timeout=timeout_ms)
            except PWTimeout: pass
        if scroll:
            auto_scroll(page)
        htmls.append(page.content())

        if next_selector:
            for _ in range(1, max_pages):
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
    v = s.get(key)
    return v if v else ""

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
        price = None
        price_el = sel_one(get_sel(sel, "price"))
        if price_el:
            raw = text(price_el).replace("\xa0"," ").replace(",",".")
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

def ocr_prices_from_image(img_bytes):
    # OCR básico: extrai números tipo 1,99 / 2.49 / € 3,79
    img = Image.open(io.BytesIO(img_bytes))
    txt = pytesseract.image_to_string(img, lang="eng+fra")
    txt = txt.replace(",", ".")
    prices = []
    for m in re.finditer(r"(\d{1,3}(?:\.\d{1,2}))\s*€|€\s*(\d{1,3}(?:\.\d{1,2}))", txt):
        val = m.group(1) or m.group(2)
        try:
            prices.append(float(val))
        except:
            pass
    # nome aproximado: linhas com letras maiúsculas / palavras longas perto de preços
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    guess_name = ""
    if lines:
        lines_sorted = sorted(lines, key=len, reverse=True)
        guess_name = lines_sorted[0][:120]
    return prices, guess_name

def scrape_leaflet_images(url, image_selector, base_url, store_name, store_code, country, fetched_at):
    # carrega a página e junta todas as imagens para OCR
    htmls = fetch_rendered_pages(url, wait_selector=image_selector, scroll=True, timeout_ms=35000)
    soup = BeautifulSoup(" ".join(htmls), "html.parser")
    imgs = soup.select(image_selector) or []
    rows = []
    for img in imgs[:40]:  # evita excesso
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src: continue
        src = urljoin(base_url, src)
        try:
            b = http_bytes(src)
            prices, gname = ocr_prices_from_image(b)
            for p in prices[:8]:
                uid = slugify(gname, f"{p:.2f}", "cactus")
                rows.append({
                    "ProductUID": uid,
                    "EAN": "",
                    "NomeProduto": gname if gname else "Promo Cactus",
                    "Loja": store_name,
                    "Store": store_code,
                    "Country": country,
                    "Preco": p,
                    "Moeda": "EUR",
                    "PrecoUnidade": "",
                    "Unidade": "",
                    "IsPromo": "TRUE",
                    "ValidadeDe": "",
                    "ValidadeAte": "",
                    "SourceURL": src,
                    "SourceType": "folheto",
                    "FetchedAt": fetched_at
                })
        except Exception:
            continue
    return rows

def main():
    print(">> Running scrape_stores.py v4.0")
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
            next_sel = src.get("next_selector")
            max_pages = int(src.get("max_pages", 3))
            open_first_folder = bool(src.get("open_first_folder"))
            image_selector = src.get("image_selector")
            if not url or not stype: continue

            try:
                if stype == "leaflet_images" and image_selector:
                    rows = scrape_leaflet_images(url, image_selector, base, name, code, country, now)
                    ofertas_rows.extend(rows)
                    continue

                pages_html = []
                if stype == "pdf":
                    pages_html = []
                else:
                    wait_sel = sel.get("card")
                    if render:
                        pages_html = fetch_rendered_pages(
                            url,
                            wait_selector=wait_sel,
                            scroll=scroll,
                            next_selector=next_sel,
                            max_pages=max_pages,
                            open_first_folder=open_first_folder
                        )
                    else:
                        pages_html = [http(url)]
            except Exception as e:
                print(f"[{code}] erro {e} em {url}")
                continue

            if DEBUG_HTML:
                for p_i, h in enumerate(pages_html):
                    path = os.path.join(DEBUG_DIR, f"{code}_{idx:02d}_{p_i:02d}.html")
                    try:
                        with open(path,"w",encoding="utf-8") as f: f.write(h)
                    except Exception:
                        pass

            for html in pages_html:
                items = []
                if stype in ("category", "offers_page"):
                    items = parse_cards(html, sel, base)
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
            time.sleep(0.25 + random.random()*0.25)

    # write outputs
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
