import os, csv, json, asyncio, re
from pathlib import Path
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright, Response
from utils import slugify, is_debug, now_iso

OUT_DIR = Path("out"); OUT_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR = OUT_DIR / "debug"; DEBUG_DIR.mkdir(parents=True, exist_ok=True)
SHOT_DIR = OUT_DIR / "shots"; SHOT_DIR.mkdir(parents=True, exist_ok=True)
OFERTAS_FULL = OUT_DIR / "ofertas_full.csv"

# Categorias por loja (podes ampliar depois)
CATEGORIES = {
    "AUCHAN": [
        "https://www.auchan.lu/fr/epicerie-salee",
        "https://www.auchan.lu/fr/epicerie-sucree",
        "https://www.auchan.lu/fr/boissons",
        "https://www.auchan.lu/fr/cremerie",
        "https://www.auchan.lu/fr/surgeles",
    ],
    "COLRUYT": [
        "https://www.colruyt.lu/fr-lu/produits?page=1",
        "https://www.colruyt.lu/fr-lu/produits?page=2",
    ],
    "DELHAIZE": [
        "https://www.delhaize.lu/fr/promos-de-la-semaine",
    ],
    # ALDI: abrir hub e navegar por TODAS as subcategorias
    "ALDI": [
        "https://www.aldi.lu/fr/produits.html",
    ],
    "LIDL": [
        "https://www.lidl.lu/c/fr-LU/offres-de-la-semaine/c9504",
    ],
    "MONOPRIX": [
        "https://www.monoprix.lu/",
    ],
}

# Env: TOR e escolha de browser por domínio (para Auchan/Colruyt/Delhaize)
USE_TOR_FOR = {d.strip().lower() for d in os.getenv("USE_TOR_FOR","").split(",") if d.strip()}

def parse_browser_map(s: str):
    m={}
    for pair in s.split(";"):
        if "=" in pair:
            d,b = pair.split("=",1)
            m[d.strip().lower()] = b.strip().lower()
    return m

BROWSER_FOR = parse_browser_map(os.getenv("BROWSER_FOR",""))

# Heurísticas
NAME_KEYS  = {"name", "title", "product_name", "label"}
PRICE_KEYS = {"price", "current_price", "amount", "value", "prix", "finalPrice"}
SIZE_KEYS  = {"size", "quantity", "pack_size", "format"}
PROMO_KEYS = {"promo", "promotion", "is_promo", "in_promo", "isPromotion"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/123.0 Safari/537.36",
    "Accept-Language": "fr-LU,fr;q=0.9,en;q=0.8,pt;q=0.7",
}
MONEY = re.compile(r"(\d+(?:[.,]\d{1,2}))")

def save_debug(name: str, content: bytes|str):
    p = DEBUG_DIR / name
    if isinstance(content, (bytes, bytearray)): p.write_bytes(content)
    else: p.write_text(content, encoding="utf-8")

def pick(d: dict, keys: set):
    for k in list(d.keys()):
        if str(k).lower() in keys: return d[k]
    return None

def coerce_price(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, str):
        v2 = v.replace("\xa0", " ").replace(",", ".")
        m = MONEY.search(v2)
        if m:
            try: return float(m.group(1))
            except: return None
    return None

def to_text(v):
    if v is None: return ""
    if isinstance(v, (int, float)): return str(v)
    return str(v).strip()

def walk_json(obj, found):
    if isinstance(obj, dict):
        name = pick(obj, NAME_KEYS); price = pick(obj, PRICE_KEYS)
        if name is not None and price is not None:
            size = pick(obj, SIZE_KEYS); promo = pick(obj, PROMO_KEYS)
            found.append({
                "name": to_text(name),
                "price": coerce_price(price),
                "size": to_text(size),
                "is_promo": str(promo).lower() in {"true","1","yes","y"} if promo is not None else False
            })
        for v in obj.values(): walk_json(v, found)
    elif isinstance(obj, list):
        for it in obj: walk_json(it, found)

async def scroll_to_bottom(page, step=1200, max_scrolls=60):
    last = 0
    for _ in range(max_scrolls):
        await page.evaluate(f"window.scrollBy(0, {step});")
        await page.wait_for_timeout(800)
        h = await page.evaluate("document.body.scrollHeight")
        if h == last: break
        last = h

async def load_more(page):
    # "Voir plus" / "Afficher plus" / "More"
    for _ in range(30):
        btn = await page.query_selector(
            "button:has-text('Plus'), button:has-text('Voir plus'), "
            "button:has-text('Afficher plus'), button:has-text('More'), "
            "a:has-text('Plus'), a:has-text('More'), a:has-text('Afficher plus')"
        )
        if not btn: break
        try:
            await btn.click(); await page.wait_for_timeout(1500)
        except: break

async def accept_cookies(page):
    # 1) na página principal
    selectors = [
        "#onetrust-accept-btn-handler","button#onetrust-accept-btn-handler",
        "button:has-text('Accepter tout')","button:has-text('Tout accepter')",
        "button:has-text('Accept All')","button:has-text('J’accepte')","button:has-text(\"J'accepte\")",
        "[aria-label*='accept']","button.cm-btn--primary",
        ".didomi-continue-without-agreeing","button:has-text('OK')",
    ]
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            try: await el.click(); await page.wait_for_timeout(400)
            except: pass
    # 2) iframes (OneTrust/Didomi)
    for frame in page.frames:
        try:
            el = await frame.query_selector("#onetrust-accept-btn-handler, button:has-text('Accepter tout'), button:has-text('Accept All')")
            if el:
                try: await el.click(); await page.wait_for_timeout(400)
                except: pass
        except: pass

async def parse_ld_json(page):
    items=[]
    for h in await page.query_selector_all("script[type='application/ld+json']"):
        try:
            data = json.loads(await h.inner_text())
            arr = data if isinstance(data, list) else [data]
            for d in arr:
                if isinstance(d, dict) and (d.get('@type')=='Product' or 'offers' in d):
                    name = to_text(d.get('name','')); size = to_text(d.get('size') or d.get('sku') or '')
                    price=None; offers = d.get('offers')
                    if isinstance(offers, dict): price = coerce_price(offers.get('price'))
                    elif isinstance(offers, list) and offers: price = coerce_price(offers[0].get('price'))
                    if name: items.append({"name":name,"price":price,"size":size,"is_promo":False})
        except: pass
    return items

def make_rows(extracted, store, url):
    now = now_iso(); rows=[]
    for it in extracted:
        nm = it.get("name","").strip(); pr = it.get("price", None); sz = it.get("size","").strip()
        if not nm: continue
        uid = slugify(nm, sz)
        rows.append({
            "ProductUID": uid, "NomeProduto": nm, "Loja": store,
            "Preco": pr if pr is not None else "", "Moeda": "EUR",
            "PrecoUnidade": "","Unidade": "",
            "IsPromo": "TRUE" if it.get("is_promo") else "FALSE",
            "ValidadeDe": "","ValidadeAte": "",
            "SourceURL": url, "FetchedAt": now
        })
    return rows

def host_of(url: str) -> str:
    try: return urlparse(url).netloc.lower()
    except: return ""

def proxy_for(url: str):
    h = host_of(url)
    for dom in USE_TOR_FOR:
        if h.endswith(dom): return {"server": "socks5://127.0.0.1:9050"}
    return None

def browser_for(url: str):
    h = host_of(url)
    for dom, br in BROWSER_FOR.items():
        if h.endswith(dom):
            return br  # "chromium" | "firefox" | "webkit"
    return "chromium"

# ─────────────────────────────────────────────────────────────
# ALDI — 1) recolhe subcategorias; 2) visita e extrai produtos
# ─────────────────────────────────────────────────────────────
async def aldi_collect_category_links(page, base_url: str) -> list[str]:
    origin = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    links = set()
    anchors = await page.query_selector_all("a[href*='/fr/produits/']")
    for a in anchors:
        href = await a.get_attribute("href")
        if not href: continue
        if href.endswith("produits.html"):  # evita o hub
            continue
        url = urljoin(origin, href)
        if "/fr/produits/" in url:
            links.add(url)
    # cartões de categoria
    anchors2 = await page.query_selector_all(".mod-category-tile a, .category-tile a, .tile a")
    for a in anchors2:
        href = await a.get_attribute("href")
        if not href: continue
        if href.endswith("produits.html"): continue
        url = urljoin(origin, href)
        if "/fr/produits/" in url:
            links.add(url)
    return sorted(links)

async def aldi_parse_category_page(context, url: str, store: str) -> list[dict]:
    page = await context.new_page()
    extracted=[]
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=90000)
        await accept_cookies(page)
        await page.wait_for_timeout(800)
        await scroll_to_bottom(page); await load_more(page); await scroll_to_bottom(page)

        # ld+json (se existir)
        ld = await parse_ld_json(page)
        if ld: extracted.extend(ld)

        # DOM oficial do ALDI (SAP Commerce)
        cards = await page.query_selector_all(".mod-article-tile, .product, .product-card, [data-test='product-tile']")
        for c in cards:
            name_el = await c.query_selector(".mod-article-tile__title, .product-title, .title, [data-test='product-title']")
            price_el= await c.query_selector(".mod-article-tile__price, .price, [data-test='product-price'], [class*='price']")
            size_el = await c.query_selector(".mod-article-tile__subtitle, .subtitle, .product-size, [data-test='product-subtitle']")
            name = (await name_el.inner_text()).strip() if name_el else ""
            price_txt = (await price_el.inner_text()).strip() if price_el else ""
            size = (await size_el.inner_text()).strip() if size_el else ""
            price=None
            if price_txt:
                m = re.search(r"(\d+(?:[.,]\d{1,2}))", price_txt.replace("\xa0"," ").replace(",",".")) 
                if m:
                    try: price=float(m.group(1))
                    except: price=None
            if name:
                extracted.append({"name":name,"price":price,"size":size,"is_promo":False})

        # debug da categoria
        try:
            await page.screenshot(path=str(SHOT_DIR / f"ALDI_{slugify(url)[:80]}.png"), full_page=True)
            html = await page.content()
            save_debug(f"html_ALDI_{slugify(url)[:80]}.html", html)
        except: pass

    except Exception as e:
        print(f"[ALDI] erro em categoria {url}: {e}")
    finally:
        await page.close()

    return make_rows(extracted, store, url)

# ─────────────────────────────────────────────────────────────

async def fetch_category(play, url: str, store: str):
    offers = []
    proxy = proxy_for(url)
    br_name = browser_for(url)
    browser_type = {"chromium": play.chromium, "firefox": play.firefox, "webkit": play.webkit}.get(br_name, play.chromium)

    browser = await browser_type.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled","--no-sandbox","--disable-dev-shm-usage"],
    )
    context = await browser.new_context(
        extra_http_headers=HEADERS, locale="fr-LU", timezone_id="Europe/Luxembourg", proxy=proxy,
        viewport={"width": 1366, "height": 768}
    )
    page = await context.new_page()

    collected_json = []
    async def on_response(resp: Response):
        try:
            if resp.request.resource_type in {"xhr","fetch"}:
                body = await resp.text()
                if body and (body.lstrip().startswith("{") or body.lstrip().startswith("[")):
                    try:
                        data = json.loads(body)
                        collected_json.append((resp.url, data))
                        if is_debug():
                            sample = json.dumps(data)[:200000].encode("utf-8")
                            save_debug(f"net_{store}_{slugify(resp.url)[:80]}.json", sample)
                    except: pass
        except: pass
    page.on("response", on_response)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=120000)
        await accept_cookies(page)
        await page.wait_for_timeout(1200)
        await scroll_to_bottom(page); await load_more(page); await scroll_to_bottom(page)

        # ALDI hub: recolhe subcategorias e percorre cada uma
        if store == "ALDI" and "/produits.html" in url:
            subcats = await aldi_collect_category_links(page, url)
            print(f"[ALDI] {len(subcats)} subcategorias encontradas")
            for link in subcats:
                rows = await aldi_parse_category_page(context, link, store)
                offers.extend(rows)
            # debug do hub
            try:
                await page.screenshot(path=str(SHOT_DIR / f"{store}_{slugify(url)[:80]}.png"), full_page=True)
                html = await page.content()
                save_debug(f"html_{store}_{slugify(url)[:80]}.html", html)
            except: pass
            await context.close(); await browser.close()
            return offers

        # screenshot (demais lojas)
        try:
            await page.screenshot(path=str(SHOT_DIR / f"{store}_{slugify(url)[:80]}.png"), full_page=True)
        except: pass

        extracted=[]
        # 1) JSON capturado
        for u, data in collected_json:
            tmp=[]; walk_json(data, tmp)
            if tmp: extracted.extend(tmp)
        # 2) LD+JSON
        if not extracted:
            try:
                ld = await parse_ld_json(page)
                if ld: extracted.extend(ld)
            except: pass
        # 3) DOM genérico
        if not extracted:
            cards = await page.query_selector_all(
                ".product, .product-card, li.product-item, .product-grid__item, "
                "[data-test='product-tile'], .tile, .mod-article-tile"
            )
            for c in cards:
                name_el = await c.query_selector(
                    ".product-title, .product-item-name, .product__title, .title, "
                    "[data-test='product-title'], .mod-article-tile__title"
                )
                price_el= await c.query_selector(
                    ".price, .product-price, .product__price, .price__amount, "
                    "[data-test='product-price'], .mod-article-tile__price, [class*='price']"
                )
                size_el = await c.query_selector(
                    ".size, .product-size, .product__size, .subtitle, "
                    "[data-test='product-subtitle'], .mod-article-tile__subtitle, [class*='size']"
                )
                name = (await name_el.inner_text()).strip() if name_el else ""
                price_txt = (await price_el.inner_text()).strip() if price_el else ""
                size = (await size_el.inner_text()).strip() if size_el else ""
                price=None
                if price_txt:
                    m = re.search(r"(\d+(?:[.,]\d{1,2}))", price_txt.replace("\xa0"," ").replace(",",".")) 
                    if m:
                        try: price=float(m.group(1))
                        except: price=None
                if name: extracted.append({"name":name,"price":price,"size":size,"is_promo":False})

        try:
            html = await page.content()
            save_debug(f"html_{store}_{slugify(url)[:80]}.html", html)
        except: pass

        offers.extend(make_rows(extracted, store, url))

    except Exception as e:
        print(f"[{store}] erro em {url}: {e}")
    finally:
        await context.close(); await browser.close()

    return offers

async def run_all():
    all_offers=[]
    async with async_playwright() as play:
        for store, urls in CATEGORIES.items():
            for url in urls:
                tor = "[TOR]" if proxy_for(url) else ""
                br  = browser_for(url)
                print(f"[{store}] -> {url} {tor} ({br})")
                offs = await fetch_category(play, url, store)
                print(f"[{store}] +{len(offs)}")
                all_offers.extend(offs)

    cols = ["ProductUID","NomeProduto","Loja","Preco","Moeda","PrecoUnidade","Unidade","IsPromo","ValidadeDe","ValidadeAte","SourceURL","FetchedAt"]
    with open(OFERTAS_FULL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in all_offers: w.writerow(r)
    print(f"✅ ofertas_full.csv: {len(all_offers)} linhas")

# helpers de proxy/browser/host
def proxy_for(url: str):
    h = host_of(url)
    for dom in USE_TOR_FOR:
        if h.endswith(dom): return {"server": "socks5://127.0.0.1:9050"}
    return None

def browser_for(url: str):
    h = host_of(url)
    for dom, br in BROWSER_FOR.items():
        if h.endswith(dom):
            return br  # "chromium" | "firefox" | "webkit"
    return "chromium"

def host_of(url: str) -> str:
    try: return urlparse(url).netloc.lower()
    except: return ""

if __name__ == "__main__":
    asyncio.run(run_all())
