# Black Point Roma

Sistema di identificazione, classificazione e visualizzazione dei siti ad alta
concentrazione incidentale (black spot e black section) sulla rete stradale di
Roma Capitale, basato sulla metodologia **Empirical Bayes** con **indice
composito di priorita'**.

La specifica dettagliata della metodologia, dei dati di input, dei modelli
statistici e dell'interfaccia di visualizzazione e' in
[`piano_progetto_blackpoint.md`](piano_progetto_blackpoint.md).

## Stato del progetto

Lo scaffolding del repository e' in piedi. Gli script della pipeline sono
attualmente **stub** che sollevano `NotImplementedError`: verranno
implementati uno step alla volta seguendo le fasi del piano.

## Prerequisiti

- Python **3.11+**
- I pacchetti di sistema necessari a `geopandas` (GDAL, GEOS, PROJ)
- I dataset di input nelle posizioni indicate in `config.yaml` -> `paths.raw`

## Installazione

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Struttura del repository

```
blackpoints/
|-- config.yaml                # tutti i parametri della pipeline
|-- run_pipeline.sh            # orchestratore (esegue gli step in sequenza)
|-- requirements.txt
|-- piano_progetto_blackpoint.md
|-- src/
|   |-- config.py              # caricatore di config.yaml
|   |-- s00_pulizia_incidenti.py
|   |-- s01_preparazione_rete.py
|   |-- s02_matching.py
|   |-- s03_spf.py
|   |-- s04_empirical_bayes.py
|   |-- s05_indice_composito.py
|   |-- s06_export.py
|   `-- utils/
|       |-- geo_utils.py
|       |-- stats_utils.py
|       `-- viz_utils.py
|-- data/
|   |-- raw/                   # dati originali (non versionati)
|   |-- interim/               # output intermedi della pipeline
|   `-- processed/             # output finali
|-- dashboard/                 # prototipo Dash
|-- notebooks/                 # analisi esplorative
|-- reports/                   # template e output di reporting
`-- tests/
```

## Esecuzione della pipeline

```bash
bash run_pipeline.sh
```

Lo script esegue in sequenza gli step `s00..s06`. Ogni step legge il proprio
input dalla cartella `data/interim/` (o `data/raw/` per il primo step) e
scrive il proprio output nello stesso `data/interim/` (o in `data/processed/`
per gli step finali).

## Test

```bash
python -m pytest tests/ -q
```

Lo smoke test verifica che tutti i moduli `src.*` siano importabili.

## Riferimenti

- Specifica metodologica e tecnica: [`piano_progetto_blackpoint.md`](piano_progetto_blackpoint.md)
