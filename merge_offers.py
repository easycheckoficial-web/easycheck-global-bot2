import csv
from pathlib import Path

IN_FULL   = Path("out/ofertas_full.csv")
OUT_SNAP  = Path("out/ofertas_snapshot.csv")
OUT_PROMO = Path("out/promocoes.csv")

COLS = ["ProductUID","NomeProduto","Loja","Preco","Moeda","PrecoUnidade","Unidade","IsPromo","ValidadeDe","ValidadeAte","SourceURL","FetchedAt"]

def read_csv(path):
    if not path.exists(): return []
    with path.open("r",encoding="utf-8") as f:
        return list(csv.DictReader(f))

def write_csv(path, cols, rows):
    path.parent.mkdir(exist_ok=True)
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)

def main():
    full = read_csv(IN_FULL)

    # último preço por ProductUID+Loja
    last = {}
    for r in full:
        key = (r.get("ProductUID",""), r.get("Loja",""))
        last[key] = r
    snap = list(last.values())

    promos = [r for r in full if (r.get("IsPromo","").upper() == "TRUE")]

    write_csv(OUT_SNAP, COLS, snap)
    write_csv(OUT_PROMO, COLS, promos)
    print(f"✅ ofertas_snapshot.csv: {len(snap)}")
    print(f"✅ promocoes.csv: {len(promos)}")

if __name__ == "__main__":
    main()
