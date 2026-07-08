#!/usr/bin/env bash
#
# Orchestratore della pipeline Black Point Roma.
# Esegue in sequenza gli step s00..s06. Ogni step legge i propri input
# da data/raw/ o data/interim/ e scrive i propri output in data/interim/
# o data/processed/.
#
# Allo stato attuale (scaffolding) ogni step solleva NotImplementedError:
# l'esecuzione di questo script si fermera' al primo step finche' non
# verra' implementato. Questo e' atteso.

set -euo pipefail

cd "$(dirname "$0")"

# Step condizionali: eseguiti solo se i loro dati raw sono presenti
# (il censimento serve al modulo Equita', non alla pipeline black point).
if [[ -f "data/raw/censimento/Sezioni_ISTAT.gpkg" ]]; then
    echo "=========================================="
    echo ">>> Esecuzione: src.s0c_censimento"
    echo "=========================================="
    python -m src.s0c_censimento
fi

STEPS=(
    "src.s00_pulizia_incidenti"
    "src.s01_preparazione_rete"
    "src.s02_matching"
    "src.s03_spf"
    "src.s04_empirical_bayes"
    "src.s05_indice_composito"
    "src.s07_hin"
    "src.s06_export"
)

for step in "${STEPS[@]}"; do
    echo "=========================================="
    echo ">>> Esecuzione: ${step}"
    echo "=========================================="
    python -m "${step}"
done

echo "Pipeline completata con successo."
