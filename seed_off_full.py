import os, csv, math, time, requests, re
from urllib.parse import urlencode
from utils import slugify

OUT_DIR = "out"
OUT_PATH = os.path.join(OUT_DIR, "produtos_off.csv")

OFF_URL = "https://world.openfoodfacts.org/cgi/search.pl"
FIELDS  = ["code","product_name","brands","quantity","image_url","scans_n","stores","countries","nutriscore_score","nutriscore_grade","nutriments","price"]

COUNTRIES = ["luxembourg","belgium","france","germany"]

def fetch_off_page(page, country):
    params = {
        "action":"process","json":1,"page_size":200,"page":page,
        "fields":",".join(FIELDS),
        "tagtype_0":"countries","tag_contains_0":"contains","tag_0":country,
        "sort_by":"unique_scans_n"
    }
    url = OFF_URL+"?"+urlencode(params)
    r = requests.get(url, timeout=30); r.raise_for_status()
    return r.json()

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    seen=set(); rows=[]
    for country in COUNTRIES:
        for page in range(1, 21):  # até 4000 produtos por país
            data = fetch_off_page(page, country)
            prods = data.get("products", [])
            if not prods: break
            for p in prods:
                ean = str(p.get("code","")).strip()
                name = (p.get("product_name") or "").strip()
                brand= (p.get("brands") or "").split(",")[0].strip()
                qty  = (p.get("quantity") or "").strip()
                img  = (p.get("image_url") or "").strip()
                scans= int(p.get("scans_n") or 0)
                uid  = ean if ean else slugify(name, brand, qty)
                if not uid or uid in seen or not name: continue
                rows.append({
                    "UID": uid, "EAN": ean, "Nome": name, "Marca": brand,
                    "Rayon": "", "SousRayon": "", "Tamanho": qty, "Imagem": img,
                    "Fonte": "OFF", "ScoreInicial": round(5 + math.log(scans+1), 3),
                    "OFFPrice": (p.get("price") or "")
                })
                seen.add(uid)
            time.sleep(0.25)

    cols=["UID","EAN","Nome","Marca","Rayon","SousRayon","Tamanho","Imagem","Fonte","ScoreInicial","OFFPrice"]
    with open(OUT_PATH,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)
    print(f"✅ produtos_off.csv ({len(rows)} itens)")

if __name__=="__main__":
    main()
