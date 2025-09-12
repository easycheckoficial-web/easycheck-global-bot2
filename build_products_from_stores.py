import os, csv, re

OUT_DIR = "out"
PRIMARY = os.path.join(OUT_DIR, "produtos_primary.csv")
FINAL   = os.path.join(OUT_DIR, "produtos.csv")

# Regras simples para preencher Rayon/SousRayon a partir do nome/quantidade
KEYWORD_TO_RAYON = [
    (r"tomate|banana|pomme|fruit|legume|salade|batata|alface", ("Fruits & Légumes","Gama")),
    (r"yaourt|iogurte|fromage|queijo|leite|lait|beurre|manteiga|crème|nata", ("Crèmerie / Laticínios","Gama")),
    (r"surgelé|congelad|frozen|glace|sorbet|gelado", ("Surgelés","Gama")),
    (r"pasta|massa|pâtes|arroz|riz|feijão|conserve|atum|sardinh|molho|sauce|azeite|huile|vinagre|vinaigre", ("Épicerie salée","Gama")),
    (r"sucre|açúcar|farinha|farine|céréales|cereal|biscuit|bolacha|chocolat|chocolate|bolo|gateau", ("Épicerie sucrée","Gama")),
    (r"eau|água|agua|jus|sumo|soda|cola|limonade|energy|café|cafe|thé|cha", ("Boissons","Gama")),
    (r"bébé|bebe|baby", ("Bébé","Gama")),
    (r"bio|organic", ("Bio","Gama")),
]

def infer_rayon(name, brand, qty):
    t = f"{name} {brand} {qty}".lower()
    for pat,(r,s) in KEYWORD_TO_RAYON:
        if re.search(pat,t): return r,s
    return "Épicerie salée","Gama"

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
    if not base:
        print("⚠️ produtos_primary.csv vazio — primeiro corre o scrape das lojas.")
    # completa Rayon/SousRayon se vierem vazios
    for uid, r in base.items():
        if (r.get("Rayon","") or "").strip(): 
            continue
        rayon, sous = infer_rayon(r.get("Nome",""), r.get("Marca",""), r.get("Tamanho",""))
        r["Rayon"], r["SousRayon"] = rayon, sous

    cols=["UID","EAN","Nome","Marca","Rayon","SousRayon","Tamanho","Imagem","Fonte","ScoreInicial"]
    with open(FINAL,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in base.values(): w.writerow(r)
    print(f"✅ produtos.csv criado a partir das LOJAS ({len(base)} itens).")

if __name__=="__main__":
    main()
