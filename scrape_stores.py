# === scrape_stores.py — VERSION v3.0 (requests + Playwright opcional) ===
import os, re, csv, time, datetime, requests, yaml
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from utils import parse_qty, unit_price, slugify

# Playwright (renderização de páginas JS quando necessário)
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

OUT_DIR = "out"
OFERTAS_FULL = os.path.join(OUT_DIR, "ofertas_full.csv")
PROD_PRIMARY = os.path.join(OUT_DIR, "produtos_primary.csv")

# Headers mais “reais” para reduzir 403
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

REQ_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
    "Cache-Control": "no-cache",
}

def http(url):
    """Fetch simples via requests (para páginas estáticas)."""
    r = requests.get(url, timeout=30, headers=REQ_HEADERS)
    r.raise_for_status()
    return r.text

def fetch_rendered_html(url, wait_selector=None, timeout_ms=20000):
    """Abre a página em Chromium headless e devolve o HTML renderizado."""
    html = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="fr-FR")
        page = ctx.new_page()
        page.goto(url, wait_until="load", timeout=timeout_ms)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            except PWTimeout:
                # mesmo sem o seletor, devolvemos o conteúdo atual
                pass
        html = page.content()
        browser.close()
    return html

def load_config(path="stores.yml"):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("stores", [])

def text(el):
    return el.get_text(" ", strip=True) if el else ""

def get_sel(s, key):
    val = s.get(key)
    return val if val else ""

def parse_cards(html, sel, base_url):
    """Extrai items (nome, preço, etc.) de uma página com cards de produto."""
    soup = BeautifulSoup(html or "", "html.parser")
    cards = soup.select(sel["card"]) if sel.get("card") else []
    out = []

    for c in cards:
        # helpers seguros (não chamam select_one com string vazia)
        def sel_one(selector):
            if not selector:
                return None
            try:
                return c.select_one(selector)
            except Exception:
                return None

        def sel_attr_img(selector):
            el = sel_one(selector)
            if not el:
                return ""
            if el.has_attr("src"): return urljoin(base_url, el["src"])
            if el.has_attr("data-src"): return urljoin(base_url, el["data-src"])
            if el.has_attr("data-original"): return urljoin(base_url, el["data-original"])
            return ""

        def sel_href(selector):
            el = sel_one(selector)
            if el and el.has_attr("href"):
                return urljoin(base_url, el["href"])
            return ""

        title_el = sel_one(get_sel(sel, "title"))
        name = text(title_el)
        if not name:
            continue

        brand = text(sel_one(get_sel(sel, "brand")))
        qty   = text(sel_one(get_sel(sel, "qty")))

        price_el = sel_one(get_sel(sel, "price"))
        price = None
        if price_el:
            # captura números tipo "1,99" ou "2.49"
            raw = text(price_el).replace(",", ".")
            m = re.search(r"(\d+(?:\.\d+)?)", raw)
            if m:
                try:
                    price = float(m.group(1))
                except ValueError:
                    price = None

        promo = bool(sel_one(get_sel(sel, "promo")))
        url   = sel_href(get_sel(sel, "link"))
        img   = sel_attr_img(get_sel(sel, "image"))
        ean   = ""  # geralmente não aparece nos cards

        out.append({
            "name": name, "brand": brand, "qty": qty, "price": price,
            "promo": promo, "url": url, "img": img, "ean": ean
        })
    return out

def main():
    print(">> Running scrape_stores.py VERSION v3.0")
    os.makedirs(OUT_DIR, exist_ok=True)
    stores = load_config()

    ofertas_rows = []
    produtos_map = {}  # UID -> produto

    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    for store in stores:
        code     = store.get("code", "STORE")
        name     = store.get("name", code)
        country  = store.get("country", "LU")
        base     = store.get("base_url", "")
        sel      = store.get("selectors", {})
        sources  = store.get("sources", [])

        for src in sources:
            stype  = src.get("type")
            url    = src.get("url")
            render = bool(src.get("render"))  # se true -> usar Playwright
            if not url or not stype:
                continue

            # 1) obter HTML (requests simples OU browser)
            html = ""
            try:
                if stype == "pdf":
                    html = ""  # parse de PDF seria noutro caminho (futuro)
                else:
                    wait_sel = sel.get("card")
                    html = fetch_rendered_html(url, wait_selector=wait_sel) if render else http(url)
            except requests.HTTPError as e:
                print(f"[{code}] HTTP error {e} em {url}")
                continue
            except Exception as e:
                print(f"[{code}] erro ao abrir {url}: {e}")
                continue

            # 2) extrair itens da listagem
            items = []
            if stype in ("category", "offers_page"):
                items = parse_cards(html, sel, base)
            elif stype == "pdf":
                items = []  # implementar quando tivermos links diretos de PDF
            else:
                continue

            # 3) montar linhas de ofertas + catálogo primário
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
                    "IsPromo": "TRUE" if it["promo"] or stype in ("offers_page","pdf") else "FALSE",
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
                        "Fonte": code,            # veio da própria loja
                        "ScoreInicial": 5.0
                    }

            time.sleep(0.2)  # polidez

    # 4) escrever ofertas_full
    cols_o = ["ProductUID","EAN","NomeProduto","Loja","Store","Country","Preco","Moeda",
              "PrecoUnidade","Unidade","IsPromo","ValidadeDe","ValidadeAte",
              "SourceURL","SourceType","FetchedAt"]
    with open(OFERTAS_FULL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols_o)
        w.writeheader()
        for r in ofertas_rows:
            w.writerow(r)
    print(f"✅ ofertas_full.csv ({len(ofertas_rows)} linhas)")

    # 5) escrever produtos_primary
    cols_p = ["UID","EAN","Nome","Marca","Rayon","SousRayon","Tamanho","Imagem","Fonte","ScoreInicial"]
    with open(PROD_PRIMARY, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols_p)
        w.writeheader()
        for r in produtos_map.values():
            w.writerow(r)
    print(f"✅ produtos_primary.csv ({len(produtos_map)} itens)")

if __name__ == "__main__":
    main()
