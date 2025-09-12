import os, csv, datetime

OUT_DIR = "out"
FULL   = os.path.join(OUT_DIR, "ofertas_full.csv")
SNAP   = os.path.join(OUT_DIR, "ofertas_snapshot.csv")
PROMOS = os.path.join(OUT_DIR, "promocoes.csv")

def key(row): return (row.get("Store","").strip(), row.get("ProductUID","").strip())

def load_csv(path):
    if not os.path.exists(path): return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows, cols):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)

def boolish(v): return str(v).strip().upper() in ("1","TRUE","YES","SIM")

def main():
    full = load_csv(FULL)
    if not full:
        print("⚠️ ofertas_full.csv está vazio — nada a fazer.")
        return

    base_cols = list(full[0].keys())
    for needed in ["Store","ProductUID","Preco","IsPromo","SourceType","FetchedAt"]:
        if needed not in base_cols: base_cols.append(needed)

    snap = load_csv(SNAP)
    snap_map = { key(r): r for r in snap }

    promos = []

    for r in full:
        k = key(r)
        prev = snap_map.get(k)
        src_type = (r.get("SourceType","") or "").lower()
        price_now = str(r.get("Preco",""))
        promo_now = boolish(r.get("IsPromo",""))
        price_old = str(prev.get("Preco","")) if prev else ""
        promo_old = boolish(prev.get("IsPromo","")) if prev else False

        # folheto/pdf: sempre vira promoção e atualiza preço vigente
        if src_type in ("folheto","pdf"):
            e = r.copy(); e["ChangeType"]="FOLHETO"; e["OldPrice"]=price_old
            promos.append(e)
            snap_map[k] = r
            continue

        # categoria: vira promoção se mudou; sempre atualiza o vigente
        changed = (price_now != price_old) or (promo_now != promo_old) or (prev is None)
        if changed:
            e = r.copy(); e["ChangeType"]="NOVO" if prev is None else "ALTERACAO"; e["OldPrice"]=price_old
            promos.append(e)
        snap_map[k] = r

    snap_rows = list(snap_map.values())
    promo_cols = base_cols[:]
    if "ChangeType" not in promo_cols: promo_cols.append("ChangeType")
    if "OldPrice"   not in promo_cols: promo_cols.append("OldPrice")

    write_csv(SNAP, snap_rows, base_cols)
    print(f"✅ ofertas_snapshot.csv atualizado ({len(snap_rows)} linhas) → {SNAP}")

    write_csv(PROMOS, promos, promo_cols)
    print(f"✅ promocoes.csv gerado ({len(promos)} linhas) → {PROMOS}")

if __name__ == "__main__":
    main()
