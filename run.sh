#!/usr/bin/env bash
set -euo pipefail

echo "==[ Configurar git ]=="
git config --global user.name  "${GIT_USER_NAME:-csv-bot}"
git config --global user.email "${GIT_USER_EMAIL:-csv-bot@users.noreply.github.com}"

# Injeta o token do Render no remote (sem expor nos logs)
if [ -n "${RENDER_GIT_TOKEN:-}" ]; then
  REPO_URL="$(git remote get-url origin | sed 's#https://##')"
  git remote set-url origin "https://${RENDER_GIT_TOKEN}@${REPO_URL}"
fi

echo "==[ Instalar browsers se faltar ]=="
python -m playwright install --with-deps chromium || true

echo "==[ 1) Scrape lojas (gera ofertas_full.csv + produtos_primary.csv) ]=="
python scrape_stores.py || true

echo "==[ 2) Baixar TODOS os produtos do OFF (gera produtos_off.csv) ]=="
for i in 1 2 3; do
  echo "OFF tentativa #$i"
  if python seed_off_full.py; then break; fi
  sleep $((i*5))
done

echo "==[ 3) Catálogo final (lojas prioridade + OFF complemento) ]=="
python build_catalog.py

echo "==[ 4) Consolidar preços (estimativa + OFF fallback) ]=="
python merge_offers.py

echo "==[ 5) Commit & push CSVs ]=="
git add out/*.csv || true
git add out/debug/*.html || true
git commit -m "Render cron: update CSVs" || echo "nada a commitar"
git pull --rebase origin "$(git rev-parse --abbrev-ref HEAD)" || true
git push origin HEAD || true

echo "✅ Fim do run"
