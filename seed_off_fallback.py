import os, csv, math, time, requests, re
from urllib.parse import urlencode
from utils import slugify

OUT_DIR = "out"
PRIMARY = os.path.join(OUT_DIR, "produtos_primary.csv")
FINAL   = os.path.join(OUT_DIR, "produtos.csv")

OFF_URL = "https://world.openfoodfacts.org/cgi/search.pl"
FIELDS  = ["code","product_name","brands","quantity","image_url","scans_n"]

KEYWORD_TO_RAYON = [
    (r"tomate|fruta|legume|pomme|banane", ("Fruits & Légumes","Gama")),
    (r"yaourt|iogurte|queijo|fromage|leite|manteiga|butter|lait", ("Crèmerie / Laticínios","Gama")),
    (r"surgelé|congelad|frozen", ("Surgelés","Gama")),
    (r"pasta|massa|arroz|rice|atum|huile|azeite|olive|molho|sauce", ("Épicerie salée","Gama")),
    (r"sucre|açúcar|farinha|cereal|biscuit|bolacha|chocolate", ("Épicerie sucrée","Gama")),
    (r"eau|água|juice|sumo|soda|cola|beer|bière|vin|wine", ("Boissons","Gama")),
    (r"bio|organic", ("Bio","Gama")),
    (r"bébé|baby", ("Bébé","Gama")),
]

def infer_rayon(name, brand, qty):
    t = f"{name} {brand} {qty}".lower()
    for pat,(r,s) in KEYWORD_TO_RAYON:
        if re.search(pat,t): return r,s
    return "Épicerie salée","Gama"

def fetch_off_page(page, country="luxembourg"):
    params = {
        "action":"process","json":1,"page_size":200,"page":page,
        "fields":",".join(FIELDS),
        "tagtype_0":"countries","tag_contains_0":"contains","tag_0":country,
        "sort_by":"unique_scans_n"
    }
    url = OFF_URL+"?"+urlencode(params)
    r = requests.get(url, timeout=30); r.raise_for_status()
    return r.json()

def load_primary(path=PRIMARY):
    if not os.path.exists(path): return {}
    out={}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["UID"]] = r
    return out

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    base = load_primary()
    seen = set(base.keys())

    # completa catálogo com OFF: LU primeiro, depois BE/FR/DE
    countries = ["luxembourg","belgium","france","germany"]
    for c in countries:
        for page in range(1,3):
            data = fetch_off_page(page, country=c)
            for p in data.get("products",[]):
                ean = str(p.get("code","")).strip()
                if not ean.isdigit(): ean = ""
                name = (p.get("product_name") or "").strip()
                brand= (p.get("brands") or "").split(",")[0].strip()
                qty  = (p.get("quantity") or "").strip()
                img  = (p.get("image_url") or "").strip()
                scans= int(p.get("scans_n") or 0)
                uid  = ean if ean else slugify(name, brand, qty)
                if not uid or uid in seen or not name:
                    continue
                rayon, sous = infer_rayon(name, brand, qty)
                score = round(5 + math.log(scans+1), 3)
                base[uid] = {
                    "UID": uid, "EAN": ean, "Nome": name, "Marca": brand,
                    "Rayon": rayon, "SousRayon": sous, "Tamanho": qty,
                    "Imagem": img, "Fonte": "OFF", "ScoreInicial": score
                }
                seen.add(uid)
            time.sleep(0.25)

    cols=["UID","EAN","Nome","Marca","Rayon","SousRayon","Tamanho","Imagem","Fonte","ScoreInicial"]
    with open(FINAL,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in base.values(): w.writerow(r)
    print(f"✅ produtos.csv ({len(base)} itens) — mercados + OFF fallback")

if __name__=="__main__":
    main()
