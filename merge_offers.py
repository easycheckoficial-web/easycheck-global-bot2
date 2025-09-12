import os, csv, statistics

OUT_DIR = "out"
FULL   = os.path.join(OUT_DIR, "ofertas_full.csv")
SNAP   = os.path.join(OUT_DIR, "ofertas_snapshot.csv")
PROMOS = os.path.join(OUT_DIR, "promocoes.csv")
PROD   = os.path.join(OUT_DIR, "produtos.csv")

def load_csv(path):
    if not os.path.exists(path): return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows, cols):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)

def key(row): return (row.get("Store","").strip(), row.get("ProductUID","").strip())
def k_prod(row): return row.get("ProductUID","").strip()

def coerce_price(v):
    s = str(v or "").strip().replace(",", ".")
    try: return float(s)
    except: return None

def main():
    full = load_csv(FULL)
    prods = { r["UID"]: r for r in load_csv(PROD) }
    if not full and not prods:
        print("⚠️ nada para consolidar"); return

    # último valor por Store+UID
    latest = {}
    for r in full:
        latest[key(r)] = r

    # construir mapa por UID com preços de lojas
    by_uid = {}
    for r in latest.values():
        uid = k_prod(r)
        if not uid: continue
        by_uid.setdefault(uid, []).append(r)

    # preços estimados quando faltar por loja
    snap_rows = []
    promo_rows = []
    for (store, uid), row in latest.items():
        # preços das outras lojas para o mesmo UID
        peers = [coerce_price(x.get("Preco")) for x in by_uid.get(uid, []) if x.get("Store") != store]
        peers = [p for p in peers if p is not None]
        price_now = coerce_price(row.get("Preco"))
        estimated = False
        estimated_from = ""

        if price_now is None:
            if len(peers) >= 2:
                # usar mediana (robusto); se 1 peer, usa esse
                try:
                    price_now = statistics.median(peers) if len(peers) > 1 else peers[0]
                    estimated = True
                    estimated_from = ",".join(sorted(set([x.get("Store") for x in by_uid.get(uid, []) if x.get("Store") != store and coerce_price(x.get("Preco")) is not None])))
                except Exception:
                    pass

        # OFF fallback se nenhuma loja tem preço para o UID
        if price_now is None:
            # verifica se todas lojas estão sem preço
            any_store_price = any([coerce_price(x.get("Preco")) is not None for x in by_uid.get(uid, [])])
            if not any_store_price:
                offp = prods.get(uid, {}).get("OFFPrice","")
                offp = coerce_price(offp)
                if offp is not None:
                    price_now = offp
                    estimated = True
                    estimated_from = "OFF"

        # monta linha final (snapshot)
        out = dict(row)
        out["Preco"] = f"{price_now:.2f}" if price_now is not None else ""
        out["Estimated"] = "TRUE" if estimated else "FALSE"
        out["EstimatedFromStores"] = estimated_from
        snap_rows.append(out)

        # histórico de promo/alteração
        if (row.get("SourceType","") or "").lower() in ("folheto","pdf"):
            e = dict(row); e["ChangeType"]="FOLHETO"; e["OldPrice"]=""
            promo_rows.append(e)

    # adicionar produtos OFF que não apareceram em nenhuma loja (para ter preço/linha no snapshot se OFF tiver)
    for uid, pr in prods.items():
        if uid not in by_uid:
            offp = coerce_price(pr.get("OFFPrice"))
            if offp is not None:
                snap_rows.append({
                    "ProductUID": uid,
                    "EAN": pr.get("EAN",""),
                    "NomeProduto": pr.get("Nome",""),
                    "Loja": "",
                    "Store": "",
                    "Country": "LU",
                    "Preco": f"{offp:.2f}",
                    "Moeda": "EUR",
                    "PrecoUnidade": "",
                    "Unidade": "",
                    "IsPromo": "FALSE",
                    "ValidadeDe": "",
                    "ValidadeAte": "",
                    "SourceURL": "",
                    "SourceType": "OFF",
                    "FetchedAt": "",
                    "Estimated": "TRUE",
                    "EstimatedFromStores": "OFF"
                })

    # escrever
    base_cols = ["ProductUID","EAN","NomeProduto","Loja","Store","Country","Preco","Moeda",
                 "PrecoUnidade","Unidade","IsPromo","ValidadeDe","ValidadeAte",
                 "SourceURL","SourceType","FetchedAt","Estimated","EstimatedFromStores"]
    write_csv(SNAP, snap_rows, base_cols)
    print(f"✅ ofertas_snapshot.csv ({len(snap_rows)} linhas)")

    promo_cols = base_cols + ["ChangeType","OldPrice"]
    write_csv(PROMOS, promo_rows, promo_cols)
    print(f"✅ promocoes.csv ({len(promo_rows)} linhas)")

if __name__ == "__main__":
    main()
