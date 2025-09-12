import os, csv

OUT_DIR = "out"
PRIMARY = os.path.join(OUT_DIR, "produtos_primary.csv")
OFF     = os.path.join(OUT_DIR, "produtos_off.csv")
FINAL   = os.path.join(OUT_DIR, "produtos.csv")

def load(path):
    if not os.path.exists(path): return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def to_map(rows, key="UID"):
    m={}
    for r in rows:
        k = r.get(key,"")
        if k and k not in m: m[k]=r
    return m

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    primary = load(PRIMARY)  # só lojas
    off     = load(OFF)      # todos OFF

    # lojas tem prioridade de campos; OFF complementa faltas e adiciona itens inexistentes
    m = to_map(primary, "UID")
    for r in off:
        uid = r["UID"]
        if uid in m:
            for k in ["EAN","Imagem"]:
                if not (m[uid].get(k) or "").strip() and (r.get(k) or "").strip():
                    m[uid][k] = r[k]
            if not (m[uid].get("ScoreInicial") or "").strip():
                m[uid]["ScoreInicial"] = r.get("ScoreInicial","")
            # guardamos OFFPrice para fallback mais tarde
            m[uid]["OFFPrice"] = r.get("OFFPrice","")
        else:
            m[uid] = r  # entra como produto “somente OFF”

    cols=["UID","EAN","Nome","Marca","Rayon","SousRayon","Tamanho","Imagem","Fonte","ScoreInicial","OFFPrice"]
    with open(FINAL,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in m.values(): w.writerow(r)
    print(f"✅ produtos.csv ({len(m)} itens) — lojas + OFF (todos)")

if __name__=="__main__":
    main()
