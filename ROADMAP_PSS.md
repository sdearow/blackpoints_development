# Roadmap: da Black Point a Planning Support System (PSS) per la sicurezza stradale

> Documento di pianificazione. Traduce gli approfondimenti di ricerca
> (`APPROFONDIMENTI_RICERCA.md`) in un piano di sviluppo concreto, ancorato
> allo stato reale del repository `blackpoints_development`.
>
> **Claim per la conferenza:** *un Planning Support System open-source e
> interattivo che integra valutazione d'impatto, diagnosi del rischio e
> ottimizzazione equity-aware degli interventi di sicurezza stradale,
> colmando il divario tra strumenti operativi e ricerca sull'equità dei
> trasporti.*

---

## 1. Punto di partenza: non si parte da zero

Il sistema Black Point attuale (`src/s00`→`s06` + dashboard Dash a 5 tab)
implementa già i due riquadri di sinistra del ciclo delle politiche:
**MONITORAGGIO** e gran parte della **DIAGNOSI del rischio**.

```
  MONITORAGGIO            DIAGNOSI                  PRESCRIZIONE
  (database georef.)  →   rischio + equità     →    ottimizzazione       →  ┐
     [FATTO]              [rischio ~70%]             [DA FARE]              │
        ↑                 [equità 0%]                                       │
        └──────────────  VALUTAZIONE  ←── before-after ←────────────────────┘
                         [macchina EB già presente, ~40%]
```

### Stato dei quattro moduli

| Modulo (rif. approfondimenti) | Stato nel repo | Cosa manca |
|---|---|---|
| **§3 Rischio (HIN/predittivo)** | ~70%: SPF NB2 (`s03`), Empirical Bayes (`s04`), excess-EPDO + indice composito (`s05`) | HIN formale (ranking KSI/km con soglia di copertura), hotspot **NKDE** di rete, distinzione *osservato vs predetto* |
| **§2 Equità** | **0% — buco principale** | Indice di bisogno socio-demografico (censimento ISTAT), Gini / concentration index, LISA bivariata, equity priority zones, tab dedicata |
| **§4 Ottimizzazione** | 0% | MCLP rischio+equità con slider efficienza↔equità, frontiera di Pareto |
| **§1 Before-after** | ~40%: la macchina EB in `s04` è riusabile | Confronto pre/post con date interventi, ITS/CausalImpact, un caso reale |

**Conseguenza strategica:** l'equità (§2) è insieme il tassello più
originale e quello completamente mancante → è lì che va lo sforzo
principale, coerente con l'MVP raccomandato negli approfondimenti (§7:
"Equity Dashboard = cuore del paper").

### Disponibilità dati (confermata)

- ✅ **Censimento ISTAT a scala fine** (sezioni di censimento): reddito/deprivazione, età, stranieri, istruzione → abilita §2.
- ✅ **Date e geometrie degli interventi** (Zone 30 / velox / strade scolastiche) → abilita §1.
- ✅ Incidenti + rete TomTom + PGTU + semafori: già nella pipeline.

Con entrambi i dataset disponibili, **tutti e quattro i moduli sono
fattibili**: non ci limitiamo all'MVP ridotto.

---

## 2. Piano d'azione (5 fasi incrementali)

Ordine scelto per **rapporto valore-scientifico / sforzo** e coerente con
le dipendenze del ciclo (§6 approfondimenti): rischio + equità definiscono
*dove serve* → alimentano l'ottimizzazione; gli interventi realizzati
vengono valutati e chiudono il ciclo.

### Fase 0 — Verifica dati + unità spaziale
*Prerequisito analitico. Decide la fattibilità di scala di tutto il resto.*

- Agganciare geograficamente il **censimento ISTAT** (sezioni Roma) alla rete.
- Strutturare le **date/fasi degli interventi** in un file tabellare/vettoriale coerente.
- Scegliere e dichiarare l'**unità spaziale** (sezione di censimento vs quartiere vs griglia) e testare la sensibilità → **MAUP** su ≥2 scale.
- **Deliverable:** `notebooks/00_verifica_dati_equita.ipynb` + nuove voci `paths` in `config.yaml`.

### Fase 1 — Modulo Equità = `s07_equita.py` + tab "Equità" **(priorità massima)**

- **Indice di bisogno** composito = vulnerabilità sociale (censimento) × rischio (l'`excess_EPDO` già calcolato in `s05`). Attenzione a normalizzazione e pesi → analisi di sensibilità (OECD/Nardo).
- **Misure di iniquità distributiva:** curva di Lorenz + **indice di Gini**; **concentration index** (dotazione interventi vs bisogno).
- **Autocorrelazione spaziale:** Moran's I globale/locale; **LISA bivariata** (bisogno vs dotazione) → mappa dei mismatch.
- **Equity priority zones:** alto bisogno + bassa dotazione.
- **Tab dashboard "Equità":** choropleth bivariata bisogno × dotazione, cluster di iniquità, pannello che ricalcola Gini/concentration index in tempo reale sugli elementi filtrati.
- **Librerie nuove:** `esda` + `libpysal` (PySAL) per LISA/Moran; `mapclassify` per la classificazione.
- **Cautele da dichiarare nel paper:** MAUP, scelta/pesi dell'indice (sensibilità), *ecological fallacy*.

> Con **Fase 0 + 1** si ha già un paper autonomo.

### Fase 2 — Completare il Rischio: HIN + NKDE = `s03b_hin.py` / estensione `s05`
*Sforzo basso, riusa quel che c'è. Buon primo commit a basso rischio.*

- **HIN:** ranking dei segmenti per (feriti gravi + morti) per km, con soglia di copertura (es. 15% della rete = 70% dei KSI).
- **NKDE:** kernel density estimation vincolata alla rete (non euclidea).
- Layer che distingue rischio **osservato** da rischio **predetto** (SPF) → l'innovazione proattiva.
- Diventa l'input "domanda" per la Fase 3.

### Fase 3 — Ottimizzazione = `s08_ottimizzazione.py` + tab "Scenari"
*L'effetto "wow" da conferenza. Dipende da Fase 1 e 2.*

- **MCLP** (Church & ReVelle 1974) con `PuLP` o OR-Tools: dato budget N e raggio d'influenza, massimizza il rischio coperto.
- **Multi-obiettivo rischio + equità:** slider efficienza↔equità, frontiera di **Pareto** (ε-constraint o **NSGA-II** con `pymoo`).
- Confronto di scenari fianco a fianco ("efficienza pura" vs "equità pura" vs "bilanciato").
- **Cautele:** definire bene "domanda" (rischio pesato) e funzione di copertura; l'ottimo è supporto alla decisione, non sostituto; dichiarare i limiti computazionali su reti grandi.

> Con **Fase 1 + 3** si ha il paper forte.

### Fase 4 — Before-after su un caso reale = estensione `s04`
*Il più vincolato dai dati (date interventi) → ultimo, ma i dati ci sono.*

- Struttura tabellare interventi: `id, tipo, data, fase, geometria`.
- **EB before-after** (Hauer 1997) riusando la SPF già calibrata + **ITS / CausalImpact** sulle serie temporali (il database registra le date).
- Indicatori di esito per tipo: Zone 30 (velocità/85°p, feriti), velox (incidenti nel raggio, effetto halo), strade scolastiche (flussi/incidenti).
- Cruscotto "Valutazione": cliccando un intervento → indicatore prima/dopo con banda di incertezza + gruppo di controllo spaziale.

### Fase 5 — Computer vision (§5)
*Future work.* Citato nel paper come sviluppo per un secondo lavoro
(audit infrastrutturale da street-level imagery, Mapillary + segmentazione).
Nessun codice in questa iterazione.

---

## 3. Percorsi consigliati

- **MVP conferenza (minimo credibile):** Fase 0 → 1 → 3.
- **Paper forte:** + Fase 2 (rischio completo alimenta bene l'ottimizzazione).
- **Framework completo:** + Fase 4, con §5 come future work.

---

## 4. Impatto sull'architettura del repo

Nuovi moduli come estensione naturale della pipeline `sNN`:

```
src/
  s07_equita.py            # Fase 1 — indice di bisogno, Gini, LISA, equity zones
  s03b_hin.py              # Fase 2 — High Injury Network + NKDE  (o esteso in s05)
  s08_ottimizzazione.py    # Fase 3 — MCLP multi-obiettivo rischio+equità
  # s04_empirical_bayes.py → esteso con before-after (Fase 4)

dashboard/
  # nuove tab: "Equità", "Scenari/Ottimizzazione", "Valutazione"

config.yaml
  # nuove sezioni: paths.censimento, paths.interventi,
  #                equita.pesi_bisogno, ottimizzazione.budget/raggio, ...

requirements.txt
  # aggiunte: libpysal, esda, mapclassify, pulp (o ortools), pymoo
```

Principi invariati dal piano esistente: modularità, parametri in
`config.yaml` (mai hardcoded), tracciabilità per ID, riproducibilità (seed).

---

## 5. Rischi e punti d'attenzione

- **Collo di bottiglia = dato, non codice.** Aggancio geografico del censimento e georiferimento delle date interventi vanno validati in Fase 0.
- **MAUP:** dichiarare l'unità spaziale e testare ≥2 scale (indispensabile in revisione).
- **Underreporting** di pedoni/ciclisti nei dati incidenti → impatta rischio ed equità.
- **Pesi degli indici** (bisogno, ICP): analisi di sensibilità obbligatoria.
- L'ottimo matematico è **supporto** alla decisione: validare con esperti.

---

## 6. Riferimenti chiave per fase

- **§1 Before-after:** Hauer (1997); Highway Safety Manual; CMF Clearinghouse; Bernal et al. (2017, ITS); Brodersen et al. (2015, CausalImpact); Grundy et al. (2009, 20mph zones).
- **§2 Equità:** Litman (*Evaluating Transportation Equity*); Lucas (2012); Karner/Golub/Martens; concentration index; OECD/Nardo (composite indicators); PySAL/esda per LISA.
- **§3 Rischio/HIN:** FHWA Systemic Safety Tool; Vision Zero HIN (NYC/SF); Okabe & Sugihara (network spatial analysis); Besag-York-Mollié / INLA; HSM SPF.
- **§4 Ottimizzazione:** Church & ReVelle (1974, MCLP); ReVelle & Eiselt (facility location review); Deb et al. (NSGA-II); pymoo, OR-Tools.
- **Dati Italia:** incidentalità ISTAT-ACI; censimento ISTAT; OpenStreetMap per la rete.

---

## 7. Prossimo passo operativo

Fase 0: aprire `notebooks/00_verifica_dati_equita.ipynb`, caricare il
censimento ISTAT e il file interventi, sceglierne l'unità spaziale e
scriverne i percorsi in `config.yaml`. Da lì parte `s07_equita.py`.
