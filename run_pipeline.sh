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
if [[ -d "data/raw/progetti" ]]; then
    echo "=========================================="
    echo ">>> Esecuzione: src.s0d_interventi"
    echo "=========================================="
    python -m src.s0d_interventi
fi

# I moduli PSS (s08 equita', s09 ottimizzazione) girano dopo la pipeline
# principale: dipendono da censimento (s0c), interventi (s0d) e
# priorita_finale (s05/s07).
esegui_equita() {
    if [[ -f "data/interim/censimento_prep.gpkg" && -f "data/interim/interventi_prep.gpkg" ]]; then
        echo "=========================================="
        echo ">>> Esecuzione: src.s08_equita"
        echo "=========================================="
        python -m src.s08_equita
        echo "=========================================="
        echo ">>> Esecuzione: src.s09_ottimizzazione"
        echo "=========================================="
        python -m src.s09_ottimizzazione
    fi
}

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

esegui_equita

echo "Pipeline completata con successo."
