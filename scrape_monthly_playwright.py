import os, csv, json, asyncio, re
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, Response
from utils import slugify, is_debug, now_iso

OUT_DIR = Path("out"); OUT_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR = OUT_DIR / "debug"; DEBUG_DIR.mkdir(parents=True, exist_ok=True)
SHOT_DIR = OUT_DIR / "shots"; SHOT_DIR.mkdir(parents=True, exist_ok=True)

OFERTAS_FULL = OUT_DIR / "ofertas_full.csv"

# ── Config: categorias por loja (podes acrescentar)
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
    "LIDL": [
        "https://www.lidl.lu/c/fr-LU/offres-de-la-semaine/c9504",
    ],
    "ALDI": [
        "https://www.aldi.lu/fr/produits.html",
    ],
    "MONOPRIX": [
        "https://www.monoprix.lu/",
    ],
}

# Heurísticas JSON/DOM
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

def save_debug(name: str, content: str|bytes):
    p = DEBUG_DIR / name
    if isinstance(content, (bytes, bytearray)):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")

def pick(d: dict, keys: set):
    for k in list(d.keys()):
        if str(k).lower() in keys:
            return d[k]
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
    """Percorre JSON e coleta itens com nome+preço."""
    if isinstance(obj, dict):
        name = pick(obj, NAME_KEYS)
        price = pick(obj, PRICE_KEYS)
        if name is not None and price is not None:
            size = pick(obj, SIZE_KEYS)
            promo = pick(obj, PROMO_KEYS)
            found.append({
                "name": to_text(name),
                "price": coerce_price(price),
                "size": to_text(size),
                "is_promo": str(promo).lower() in {"true","1","yes","y"} if promo is not None else False
            })
        for v in obj.values():
            walk_json(v, found)
    elif isinstance(obj, list):
        for it in obj:
            walk_json(it, found)

async def scroll_to_bottom(page, step=1200, max_scrolls=50):
    last = 0
    for _ in range(max_scrolls):
        await page.evaluate(f"window.scrollBy(0, {step});")
        await page.wait_for_timeout(800)
        h = await page.evaluate("document.body.scrollHeight")
        if h == last: break
        last = h

async def load_more(page):
    # tenta clicar em "ver mais"
    for _ in range(20):
        btn = await page.query_selector("button:has-text('Plus'), button:has-text('Voir plus'), button:has-text('More'), a:has-text('Plus'), a:has-text('More')")
        if not btn: break
        try:
            await btn.click()
            await page.wait_for_timeout(1500)
        except:
            break

async def fetch_category(play, url: str, store: str):
    offers = []
    browser = await play.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = await browser.new_context(extra_http_headers=HEADERS, locale="fr-LU")
    page = await context.new_page()

    collected_json = []

    async def on_response(resp: Response):
        try:
            if resp.request.resource_type in {"xhr", "fetch"}:
                ct = (resp.headers or {}).get("content-type","")
                if "application/json" in ct or resp.url.endswith(".json"):
                    data = await resp.json()
                    collected_json.append((resp.url, data))
                    # salva uma amostra
                    sample = json.dumps(data)[:200000].encode("utf-8")
                    save_debug(f"net_{store}_{slugify(resp.url)[:80]}.json", sample)
        except Exception:
            pass

    page.on("response", on_response)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(1500)
        await scroll_to_bottom(page)
        await load_more(page)
        await scroll_to_bottom(page)

        # screenshot pra verificar o que apareceu
        try:
            shot_path = SHOT_DIR / f"{store}_{slugify(url)[:80]}.png"
            await page.screenshot(path=str(shot_path), full_page=True)
        except:
            pass

        # 1) via JSON interceptado
        extracted = []
        for u, data in collected_json:
            tmp = []
            walk_json(data, tmp)
            if tmp:
                extracted.extend(tmp)

        # 2) fallback DOM
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
                    "[data-test='product-price'], .mod-article-tile__price"
                )
                size_el = await c.query_selector(
                    ".size, .product-size, .product__size, .subtitle, "
                    "[data-test='product-subtitle'], .mod-article-tile__subtitle"
                )
                name = (await name_el.inner_text()).strip() if name_el else ""
                price_txt = (await price_el.inner_text()).strip() if price_el else ""
                size = (await size_el.inner_text()).strip() if size_el else ""
                price = None
                m = re.search(r"(\d+(?:[.,]\d{1,2}))", price_txt.replace("\xa0"," ").replace(",","."))
                if m:
                    try: price = float(m.group(1))
                    except: price = None
                if name:
                    extracted.append({"name": name, "price": price, "size": size, "is_promo": False})

        now = now_iso()
        for it in extracted:
            nm = it.get("name","").strip()
            pr = it.get("price", None)
            sz = it.get("size","").strip()
            if not nm: continue
            uid = slugify(nm, sz)
            offers.append({
                "ProductUID": uid,
                "NomeProduto": nm,
                "Loja": store,
                "Preco": pr if pr is not None else "",
                "Moeda": "EUR",
                "PrecoUnidade": "",
                "Unidade": "",
                "IsPromo": "TRUE" if it.get("is_promo") else "FALSE",
                "ValidadeDe": "",
                "ValidadeAte": "",
                "SourceURL": url,
                "FetchedAt": now
            })

        # salva HTML da página final
        try:
            html = await page.content()
            save_debug(f"html_{store}_{slugify(url)[:80]}.html", html)
        except:
            pass

    except Exception as e:
        print(f"[{store}] erro em {url}: {e}")
    finally:
        await context.close()
        await browser.close()

    return offers

async def run_all():
    all_offers = []
    async with async_playwright() as play:
        for store, urls in CATEGORIES.items():
            for url in urls:
                print(f"[{store}] -> {url}")
                off = await fetch_category(play, url, store)
                print(f"[{store}] +{len(off)} linhas")
                all_offers.extend(off)

    # escreve sempre o CSV (mesmo vazio)
    cols = ["ProductUID","NomeProduto","Loja","Preco","Moeda","PrecoUnidade","Unidade","IsPromo","ValidadeDe","ValidadeAte","SourceURL","FetchedAt"]
    with open(OFERTAS_FULL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in all_offers: w.writerow(r)
    print(f"✅ ofertas_full.csv: {len(all_offers)} linhas")

if __name__ == "__main__":
    asyncio.run(run_all())
