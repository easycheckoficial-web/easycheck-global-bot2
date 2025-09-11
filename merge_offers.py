import os, csv, datetime

OUT_DIR = "out"
FULL   = os.path.join(OUT_DIR, "ofertas_full.csv")      # gerado pelo scrape_stores.py
SNAP   = os.path.join(OUT_DIR, "ofertas_snapshot.csv")  # preço vigente por Store+Product
PROMOS = os.path.join(OUT_DIR, "promocoes.csv")         # histórico de promoções/mudanças

def key(row):
    return (row.get("Store","").strip(), row.get("ProductUID","").strip())

def load_csv(path):
    if not os.path.exists(path): return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows, cols):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)

def boolish(v):
    return str(v).strip().upper() in ("1","TRUE","YES","SIM")

def main():
    full = load_csv(FULL)
    if not full:
        print("⚠️ ofertas_full.csv está vazio — nada a fazer.")
        return

    # colunas base vindas do FULL
    base_cols = list(full[0].keys())
    # garantir algumas colunas esperadas
    for needed in ["Store","ProductUID","Preco","IsPromo","SourceType","FetchedAt"]:
        if needed not in base_cols:
            base_cols.append(needed)

    snap = load_csv(SNAP)
    snap_map = { key(r): r for r in snap }

    promos = []
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat()+"Z"

    for r in full:
        k = key(r)
        prev = snap_map.get(k)
        src_type = (r.get("SourceType","") or "").lower()      # "categoria" | "folheto" | "pdf"
        price_now = str(r.get("Preco",""))
        promo_now = boolish(r.get("IsPromo",""))

        if prev:
            price_old = str(prev.get("Preco",""))
            promo_old = boolish(prev.get("IsPromo",""))
        else:
            price_old = ""
            promo_old = False

        # Regra 1: se vier de folheto/pdf → sempre entra em Promoções
        if src_type in ("folheto","pdf"):
            e = r.copy()
            e["ChangeType"] = "FOLHETO"
            e["OldPrice"]   = price_old
            promos.append(e)
            # e atualiza o snapshot
            snap_map[k] = r
            continue

        # Regra 2: categoria → só gera Promoção se mudou preço/promo; mas sempre atualiza snapshot
        changed = (price_now != price_old) or (promo_now != promo_old) or (prev is None)
        if changed:
            e = r.copy()
            e["ChangeType"] = "NOVO" if prev is None else "ALTERACAO"
            e["OldPrice"]   = price_old
            promos.append(e)

        # Atualiza vigente
        snap_map[k] = r

    # Preparar escrita dos ficheiros
    snap_rows = list(snap_map.values())

    promo_cols = base_cols[:]
    if "ChangeType" not in promo_cols: promo_cols.append("ChangeType")
    if "OldPrice"   not in promo_cols: promo_cols.append("OldPrice")

    # Escrever SNAPSHOT (preço vigente)
    write_csv(SNAP, snap_rows, base_cols)
    print(f"✅ ofertas_snapshot.csv atualizado ({len(snap_rows)} linhas) → {SNAP}")

    # Escrever PROMOÇÕES (histórico)
    write_csv(PROMOS, promos, promo_cols)
    print(f"✅ promocoes.csv gerado ({len(promos)} linhas) → {PROMOS}")

if __name__ == "__main__":
    main()
