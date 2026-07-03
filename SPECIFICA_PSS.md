# Specifica tecnico-scientifica — Planning Support System open-source per la sicurezza stradale e la mobilità attiva

> Documento di visione e specifica di sviluppo. Descrive in modo comprensivo
> **ciò che il sistema è già** (pipeline Black Point Roma, `s00`→`s06` +
> dashboard) e **ciò che vogliamo sviluppare** (equità, rischio proattivo,
> ottimizzazione, valutazione before-after), con metodo, dati, formule,
> architettura software e cautele metodologiche.
>
> Documenti correlati:
> - `piano_progetto_blackpoint.md` — specifica della pipeline esistente.
> - `APPROFONDIMENTI_RICERCA.md` — filoni di ricerca e bibliografia.
> - `ROADMAP_PSS.md` — piano di sviluppo sintetico in 5 fasi.
> Questo documento è il riferimento unico e approfondito che li integra.

---

## Indice

1. [Visione e claim scientifico](#1-visione-e-claim-scientifico)
2. [Il sistema esistente in dettaglio](#2-il-sistema-esistente-in-dettaglio)
3. [Architettura target del PSS](#3-architettura-target-del-pss)
4. [Modulo A — Completamento della diagnosi del rischio (HIN + predittivo)](#4-modulo-a--completamento-della-diagnosi-del-rischio)
5. [Modulo B — Equità distributiva (modulo di punta)](#5-modulo-b--equità-distributiva)
6. [Modulo C — Ottimizzazione della localizzazione degli interventi](#6-modulo-c--ottimizzazione-della-localizzazione-degli-interventi)
7. [Modulo D — Valutazione before-after degli interventi](#7-modulo-d--valutazione-before-after-degli-interventi)
8. [Modulo E — Audit infrastrutturale con computer vision (future work)](#8-modulo-e--audit-infrastrutturale-future-work)
9. [Dati: esistenti e nuovi](#9-dati-esistenti-e-nuovi)
10. [Architettura software e impatto sul repo](#10-architettura-software-e-impatto-sul-repo)
11. [Cautele metodologiche trasversali](#11-cautele-metodologiche-trasversali)
12. [Roadmap e sequenza di sviluppo](#12-roadmap-e-sequenza-di-sviluppo)
13. [Riferimenti bibliografici](#13-riferimenti-bibliografici)

---

## 1. Visione e claim scientifico

Il database interattivo Black Point, di per sé, è uno strumento operativo:
identifica *dove sono accaduti* gli incidenti e li prioritizza. Il salto di
qualità scientifico è **trasformarlo in un Planning Support System (PSS) /
Spatial Decision Support System (SDSS) open-source e interattivo** costruito
attorno all'approccio *Safe System / Vision Zero*, che **chiude il ciclo delle
politiche**:

```
  MONITORAGGIO            DIAGNOSI                  PRESCRIZIONE
  (database georef.)  →   rischio + equità     →    ottimizzazione       →  ┐
        ↑                 (dove serve agire)        (dove intervenire)      │
        └──────────────  VALUTAZIONE  ←── before-after (ha funzionato?) ←───┘
```

Nessuno dei quattro moduli è nuovo in assoluto. **L'innovazione difendibile è
la loro integrazione in un unico ambiente interattivo, aperto e riproducibile,
con l'equità come criterio di primo livello — non come analisi accademica
a posteriori, ma come dimensione interattiva dentro lo strumento di
pianificazione, direttamente collegata all'ottimizzazione degli interventi.**

**Claim per la conferenza:** *un Planning Support System open-source e
interattivo che integra valutazione d'impatto, diagnosi del rischio e
ottimizzazione equity-aware degli interventi di sicurezza stradale, colmando
il divario tra strumenti operativi e ricerca sull'equità dei trasporti.*

*Keywords:* Planning Support System, Spatial Decision Support System, Vision
Zero, Safe System, evidence-based road safety, transport equity, participatory
planning tools.

---

## 2. Il sistema esistente in dettaglio

Lo stato attuale del repository copre **MONITORAGGIO** e ~70% della
**DIAGNOSI del rischio**. È una base solida, non un prototipo: una pipeline
modulare `s00`→`s06`, configurata interamente da `config.yaml`, con test e una
dashboard Dash a 5 tab. Descriverla con precisione è essenziale perché ogni
nuovo modulo vi si aggancia.

### 2.1 La pipeline dati (`src/s00`→`s06`)

**`s00_pulizia_incidenti.py` — pulizia del database incidenti (Fase 0).**
Carica tutti i CSV `Incidenti_*.csv` del Comune di Roma, deduplica su
`idprotocollo` con priorità alle ri-geolocalizzazioni annuali più recenti,
standardizza i campi e riproietta dal CRS nativo `EPSG:3004` (Gauss-Boaga) al
CRS metrico di lavoro `EPSG:32633` (UTM 33N). Prodotti chiave:
- gravità standardizzata (`mortale`, `feriti`, `solo_danni` — il dato **non**
  distingue feriti gravi da lievi, scelta che si riflette nei pesi EPDO);
- data/ora parsate (anno, mese, giorno, fascia oraria);
- flag di qualità della geocodifica (`alta`/`media`/`bassa`);
- normalizzazione toponomastica per il matching successivo.
Output: `data/interim/incidenti_clean.gpkg`.

**`s01_preparazione_rete.py` — rete TomTom + join PGTU (Fase 0).**
Carica la rete TomTom (~94.148 archi, layer `tomtom_data_2024`, geometria
`MultiLineString Z`), valida la topologia e calcola le **derivate che
alimenteranno le SPF**: `log_tgm`, `log_lunghezza`, `iqr_norm` (range
interquartile normalizzato delle velocità), `ratio_v85_limite`. Aggancia
spazialmente la **classificazione funzionale del grafo PGTU 2026** (Scorrimento,
Interquartiere, Interzonale, Quartiere, grande viabilità, TPL) e prepara i
**semafori** (con correzione di offset sistematico dx=0.9, dy=6.4 m).
Output: `rete_tomtom_prep.gpkg`, `semafori_prep.gpkg`.

**`s02_matching.py` — matching spaziale incidenti ↔ rete (Fase 1).**
Il cuore geometrico. Estrae le **intersezioni** dai nodi della rete
(union-find sui nodi a grado ≥3, filtro dei falsi incroci per carreggiate
separate/biforcazioni, clustering di prossimità, associazione semafori),
costruisce i **segmenti omogenei** (catene di archi con stesso toponimo/
topologia, spezzati alle intersezioni e dove il TGM varia oltre soglia,
lunghezza 100–2000 m) e **assegna ogni incidente** a un'intersezione o a un
segmento con snap geometrico e fallback toponomastico fuzzy (`rapidfuzz`).
Output: `intersezioni.gpkg`, `segmenti.gpkg`, `incidenti_matched.gpkg`.

**`s03_spf.py` — Safety Performance Functions (Fase 2).**
Calibra modelli **binomiali negativi (NB2)** con `statsmodels`, separatamente
per i segmenti (una SPF per categoria funzionale, con accorpamento sotto
`min_siti_per_categoria=50`) e per le intersezioni (per tipo
semaforizzata/non). Forma funzionale:

```
log(μ) = β₀ + β₁·log(TGM) + β₂·log(L) [+ β₃·V85 + β₄·IQR_norm] + offset(log n_anni)
```

Produce il valore atteso `E_i` per ogni sito, il parametro di sovradispersione
`k`, e la diagnostica. Output: `spf_models.pkl` + predizioni sui siti.

**`s04_empirical_bayes.py` — Empirical Bayes + EPDO (Fase 3).**
Corregge la **regression to the mean** combinando osservato e atteso:

```
w_i  = 1 / (1 + E_i · k)          (peso EB)
EB_i = w_i · E_i + (1 − w_i) · O_i (stima EB)
excess_i = EB_i − E_i             (eccesso atteso)
Var(EB_i) = EB_i · (1 − w_i)      (incertezza)
```

Pesa per gravità con i coefficienti **EPDO** (`mortale=12`, `feriti=3`,
`solo_danni=1` — rapporti moderati scelti per evitare che un singolo mortale
casuale domini il ranking; distinti dai costi sociali MEF/ISTAT in euro, tenuti
separati). Produce `excess_EPDO_i` e il costo sociale.
Output: `eb_results.parquet`.

**`s05_indice_composito.py` — indice composito di priorità (Fase 4).**
Costruisce quattro componenti normalizzate 0–100 (con normalizzazione robusta
P1–P99, e *zero-inflated* per i rapporti dove lo zero ha significato):
- **A** — eccesso EB pesato (`excess_EPDO_i`);
- **B** — indice di severità = (mortali + feriti gravi) / incidenti;
- **C** — indice di **vulnerabilità utenti** = (incid. con pedone o ciclista) / incidenti;
- **D** — rischio velocità = f(V85/limite, IQR_norm).

Le combina nell'**ICP** con pesi configurabili (default: ICP = componente A;
le altre pesabili interattivamente), classifica in **5 fasce di priorità**
(percentili 20/40/60/80) e costruisce la **matrice di rischio 2×2** (eccesso ×
severità → urgente / programmato / indagine / monitoraggio).
Output: `priorita_finale.gpkg`.

**`s06_export.py` — export (Fase 5/6).** GeoJSON WGS84 per la dashboard,
classifiche Excel, mappa PNG, sintesi CSV.

### 2.2 La dashboard esistente (`dashboard/`)

App **Dash/Plotly** con 5 tab:
1. **Mappa** — segmenti e intersezioni colorati per fascia/eccesso EPDO.
2. **Analisi SPF** — scatter osservato vs atteso, diagnostica dei modelli.
3. **Analisi EB** — distribuzioni dell'eccesso, top siti.
4. **Sensitività pesi** — slider dei pesi ICP, confronto ranking what-if.
5. **Vista decisionale** — matrice di rischio, classifica top-N esportabile.

### 2.3 Cosa questo significa per lo sviluppo

Tre implicazioni operative:
1. **La macchina statistica del rischio esiste già** (SPF + EB + eccesso).
   Il Modulo A la estende, non la riscrive.
2. **Esiste già una componente "vulnerabilità" (C)**, ma è la *vulnerabilità
   degli utenti coinvolti* (pedoni/ciclisti nell'incidente). L'equità del
   Modulo B è cosa diversa e complementare: la **vulnerabilità sociale del
   territorio** (chi ci vive). Vanno tenute distinte e nominate con chiarezza.
3. **La dashboard ha già il pattern degli slider what-if** (tab Sensitività):
   i nuovi controlli interattivi (slider equità↔efficienza) seguono lo stesso
   stile.

---

## 3. Architettura target del PSS

I quattro moduli attivi formano una pipeline coerente; è l'integrazione la
novità.

```
  §B Equità (indice di bisogno) ──┐
                                  ├─→ §C Ottimizzazione (rischio + equità) ─→ interventi proposti
  §A Rischio (HIN/predittivo) ────┘                                                │
                                                                                   ▼
  Database interattivo (monitoraggio) ←────────── §D Valutazione before-after ←── interventi realizzati
```

- il **rischio (A)** e l'**equità (B)** definiscono *dove serve*;
- l'**ottimizzazione (C)** propone *dove intervenire* bilanciando i due;
- gli interventi realizzati vengono monitorati nel database e **valutati (D)**;
- i risultati aggiornano rischio ed equità → il ciclo si chiude.

Ogni modulo è un nuovo step `sNN` della pipeline + una tab della dashboard,
con tutti i parametri in `config.yaml`.

---

## 4. Modulo A — Completamento della diagnosi del rischio

*(High Injury Network + hotspot di rete + rischio predittivo. Estende `s03`/`s05`.)*

### 4.1 Obiettivo e cornice
Passare da un approccio **reattivo** (hotspot dove gli incidenti sono già
accaduti) a uno **proattivo/sistemico** (dove è *probabile* che accadano, anche
senza storico). Gli incidenti gravi sono eventi rari: la mappa reattiva è
instabile e arriva sempre dopo.

### 4.2 Cosa esiste già e cosa manca
Esiste: SPF, EB, eccesso EPDO → un rischio *osservato-corretto* per sito.
Manca:
1. **High Injury Network (HIN)** — la quota minima di rete che concentra la
   maggioranza dei feriti gravi + morti.
2. **Hotspot di rete (NKDE)** — densità di incidenti *lungo la rete*.
3. Distinzione esplicita **rischio osservato vs predetto** come layer.

### 4.3 Metodo
- **HIN:** ranking dei segmenti per (KSI = morti + feriti gravi) per km;
  soglia di copertura configurabile (es. il 15% della rete che contiene il 70%
  dei KSI). La stima EB già disponibile rende il ranking più stabile della
  conta grezza.
- **Network-constrained Kernel Density Estimation (NKDE):** densità di
  incidenti calcolata sulle distanze di rete, non euclidee (fondamentale sulle
  strade). Getis-Ord Gi\* / Moran locale come cluster complementari.
- **Rischio predittivo:** la SPF già fornisce `E_i`; l'innovazione è *mapparlo
  su tutta la rete come superficie continua* e distinguerlo dall'osservato.
  Estensione futura: modelli spaziali bayesiani (BYM/INLA) o ML (XGBoost + SHAP)
  per gestire autocorrelazione, zero-inflation ed eventi rari.

### 4.4 Output e integrazione
- Nuovo attributo `is_HIN` e `rank_KSI_km` sui segmenti in `priorita_finale`.
- Layer `rischio_osservato` vs `rischio_predetto` esportati per la dashboard.
- Diventa l'**input "domanda"** del Modulo C (ottimizzazione).

### 4.5 Cautele
Underreporting di pedoni/ciclisti (sottostima sistematica del rischio dove la
mobilità attiva è alta); disponibilità dei dati di esposizione; rarità degli
eventi gravi.

*Keywords:* High Injury Network, systemic safety, network kernel density
estimation, Getis-Ord hotspot, Safety Performance Function, BYM/INLA.

---

## 5. Modulo B — Equità distributiva

*(Modulo di punta. Nuovo step `s07_equita.py` + tab "Equità". È il cuore del paper.)*

### 5.1 Perché è il modulo di punta
L'equità è oggi centrale nel dibattito sui trasporti ma **raramente è
integrata in uno strumento interattivo di pianificazione**: di solito è
un'analisi accademica separata. Portarla *dentro* il PSS, in tempo reale e
collegata all'ottimizzazione, è la mossa più originale.

### 5.2 Cornici teoriche
- **Tipi di equità** (Litman): *horizontal* (uguale a chi è uguale) vs
  **vertical** (di più a chi ha più bisogno) — è qui che si gioca la ricerca;
  *distributive* vs *procedural*.
- **Transport poverty / social exclusion** (Lucas 2012).
- **Mobility / environmental justice** (Karner, Golub, Martens).

### 5.3 Domanda di ricerca
> Gli interventi di sicurezza stradale e mobilità attiva sono distribuiti in
> modo equo rispetto al **bisogno** (rischio + vulnerabilità sociale), o
> seguono altri criteri (es. quartieri già avvantaggiati, dove i cittadini
> sanno far pressione)?

### 5.4 Metodo, passo per passo

**1. Indice di bisogno per unità territoriale.**
Combinare due assi, entrambi già parzialmente disponibili:
- **vulnerabilità sociale** (dal censimento ISTAT per sezione: reddito/
  deprivazione, % bambini 0–14, % anziani 65+, % stranieri, istruzione);
- **rischio/esposizione** (l'`excess_EPDO` e la HIN del Modulo A, densità
  pedonale, prossimità a scuole).

Costruzione come *composite index* con normalizzazione dichiarata e pesi
soggetti ad **analisi di sensibilità** (handbook OECD/Nardo).

```
bisogno_i = g( vuln_sociale_i , rischio_i )   # es. media geometrica o pesata
```

**2. Misure di disuguaglianza distributiva.**
- **Curva di Lorenz + indice di Gini** applicati alla dotazione di interventi
  rispetto alla popolazione/bisogno;
- **Concentration index** (letteratura sanitaria): misura se gli interventi si
  concentrano sui più o sui meno bisognosi. Segno negativo = pro-ricchi.

**3. Autocorrelazione spaziale e cluster.**
- **Moran's I** globale e locale (LISA) sulla dotazione di interventi;
- **LISA bivariata** (bisogno vs dotazione) → mappa dei *mismatch* (alto
  bisogno / bassa dotazione = "High-Low"). Libreria `esda` + `libpysal`.

**4. Equity priority zones.**
Aree ad **alto bisogno e bassa dotazione** → aree prioritarie. Visualizzate con
**choropleth bivariata** bisogno × dotazione.

**5. Accessibilità equa (opzionale).**
Quante persone di ciascun gruppo raggiungono infrastruttura sicura entro X
minuti.

### 5.5 La funzione interattiva (tab "Equità")
- selezione di un tipo di intervento (o tutti) e di uno strato socio-demografico;
- mappa con **choropleth bivariata** e **cluster di iniquità** (LISA bivariata);
- pannello che ricalcola **Gini / concentration index in tempo reale** sugli
  elementi filtrati;
- evidenziazione delle **equity priority zones**.

**Innovazione:** l'equità come criterio *interattivo e in tempo reale* dentro
lo strumento, non un report statico. Si collega direttamente al Modulo C, dove
diventa un obiettivo esplicito dell'ottimizzazione.

### 5.6 Output e integrazione
- `data/processed/equita.gpkg` per unità territoriale (bisogno, dotazione,
  cluster LISA, flag equity_priority);
- indici sintetici (Gini, concentration index) in un JSON per la dashboard;
- il campo `equity_priority` alimenta la funzione-obiettivo del Modulo C.

### 5.7 Cautele (cruciali in revisione)
- **MAUP** (Modifiable Areal Unit Problem): i risultati dipendono dall'unità
  spaziale → dichiararla e **testare ≥2 scale**;
- scelta e **pesi dell'indice** → analisi di sensibilità obbligatoria;
- **ecological fallacy**: no inferenze individuali da dati aggregati.

*Keywords:* transport equity, vertical equity, transport poverty, concentration
index, Gini accessibility, bivariate LISA, social vulnerability index, MAUP.

---

## 6. Modulo C — Ottimizzazione della localizzazione degli interventi

*(Rende lo strumento prescrittivo. Nuovo `s08_ottimizzazione.py` + tab "Scenari". Dipende da A e B.)*

### 6.1 Il problema
Dato un **budget limitato** e una **mappa di rischio**, dove collocare i
prossimi N interventi (velox, attraversamenti protetti, Zone 30…) per il
massimo beneficio? È un problema classico di **facility location / spatial
optimization**.

### 6.2 Formulazioni
- **Maximal Covering Location Problem (MCLP)** — massimizza la "domanda"
  (= rischio) coperta entro un raggio, con budget fisso. **La più adatta.**
  (Church & ReVelle 1974).
- *p-median*, *Location Set Covering*, varianti *capacitated* / *budget-
  constrained* / con decadimento della copertura con la distanza.

### 6.3 L'innovazione: multi-obiettivo rischio + equità
Invece di ottimizzare solo la riduzione del rischio, si ottimizza
*simultaneamente*:
- **massima riduzione del rischio** (input dal Modulo A), e
- **massima equità** (priorità alle equity priority zones del Modulo B),

eventualmente con **vincoli di equità** (es. ≥X% degli interventi in aree ad
alto bisogno). Metodi:
- **programmazione lineare intera (ILP)** con `PuLP` o OR-Tools;
- **multi-obiettivo** con **frontiera di Pareto** (ε-constraint, o NSGA-II con
  `pymoo`);
- confronto di scenari: "efficienza pura" vs "equità pura" vs "bilanciato".

### 6.4 La funzione interattiva (tab "Scenari")
- l'utente imposta budget, tipo di intervento, raggio d'influenza e il **peso
  dell'equità** (uno slider efficienza↔equità);
- lo strumento propone sulla mappa le **localizzazioni ottimali** e i trade-off
  (rischio coperto vs equità) sulla **frontiera di Pareto**;
- confronto di più scenari fianco a fianco.

**Innovazione:** uno strumento *what-if* che rende esplicito e negoziabile il
compromesso **efficienza ↔ equità** — raro in letteratura, molto efficace a
conferenza.

### 6.5 Output e cautele
Output: `scenari_ottimizzazione.gpkg` (siti proposti per scenario) + punti
della frontiera di Pareto. Cautele: definire bene "domanda" (rischio pesato) e
funzione di copertura; validare con esperti; l'ottimo matematico è **supporto**
alla decisione, non sostituto; dichiarare i limiti computazionali su reti
grandi.

*Keywords:* Maximal Covering Location Problem, facility location road safety,
multi-objective optimization Pareto, NSGA-II pymoo, equity-based facility
location, efficiency-equity trade-off.

---

## 7. Modulo D — Valutazione before-after degli interventi

*(Chiude il ciclo. Estende `s04` + nuova tab "Valutazione". Fattibile: le date interventi sono disponibili.)*

### 7.1 Il problema metodologico
Confrontare "prima" e "dopo" in modo naïve è sbagliato. Tre insidie:
**regression to the mean** (gli interventi si mettono dove gli incidenti erano
alti, e calerebbero comunque), **trend temporali** generali, **confondenti**
(meteo, traffico, altri interventi).

### 7.2 Metodi (dal più semplice al più robusto)
1. Naïve before-after — solo contesto;
2. Comparison group — gruppo di controllo di aree simili non trattate;
3. **Empirical Bayes before-after** — *standard aureo* (Hauer 1997), base
   dell'HSM. **Riusa direttamente la SPF già calibrata in `s03`** per predire
   il controfattuale;
4. Full Bayes — gerarchico, per piccoli campioni;
5. **Interrupted Time Series (ITS)** e **CausalImpact** — sulle serie temporali
   (il database registra le date → naturale);
6. Difference-in-differences / synthetic control.

### 7.3 Indicatori di esito per tipo di intervento
- **Zone 30:** velocità media/85°p, % veicoli sopra soglia, incidenti/feriti,
  rumore, qualità dell'aria (Grundy et al. 2009, 20mph zones);
- **Velox:** incidenti nel raggio d'influenza, velocità, effetto halo a valle;
- **Strade scolastiche:** qualità dell'aria agli orari di ingresso/uscita,
  flussi pedonali, incidenti, mode shift casa-scuola.

### 7.4 La funzione interattiva (tab "Valutazione")
Cliccando un intervento: indicatore prima/dopo con **banda di incertezza**,
confronto con il **gruppo di controllo** (aree simili selezionate
spazialmente), stima EB o ITS calcolata al volo o pre-calcolata.

**Innovazione:** la maggior parte delle valutazioni before-after sono studi
statici *ex-post*; qui diventano un **cruscotto vivo e riproducibile**,
aggiornato man mano che entrano nuovi dati. È il ponte fra strumento operativo
e ricerca.

### 7.5 Dati e integrazione
Richiede una tabella interventi strutturata: `id_intervento, tipo, data_inizio,
fase, geometria`. Output: `valutazioni.parquet` (stima d'effetto + IC per
intervento). Per l'MVP: **almeno un caso reale** (es. una Zona 30 con dati
prima/dopo) dà concretezza.

*Keywords:* Empirical Bayes before-after, interrupted time series, CausalImpact,
Crash Modification Factor, 20mph zones casualties, speed camera meta-analysis.

---

## 8. Modulo E — Audit infrastrutturale (future work)

*Eccellente ma impegnativo → secondo paper.* Rilevamento e classificazione di
infrastrutture (marciapiedi, attraversamenti, ciclabili, segnaletica) da
*street-level imagery* con semantic segmentation / object detection (Mapillary
Vistas, YOLO, DeepLab); valutazione di qualità/continuità; sicurezza percepita
(Place Pulse / Streetscore). Un layer "stato dell'infrastruttura" alimenterebbe
l'indice di bisogno (B) e la mappa di rischio (A). Limiti: disponibilità e
licenza delle immagini, labeling/GPU, ground truth, georiferimento. **Nessun
codice in questa iterazione** — citato come sviluppo futuro.

*Keywords:* semantic segmentation streetscape, Mapillary Vistas, pedestrian
infrastructure audit, Place Pulse perceived safety.

---

## 9. Dati: esistenti e nuovi

| Dato | Stato | Usato da |
|---|---|---|
| Incidenti georeferenziati (Comune di Roma, CSV, 2004–2024) | ✅ in pipeline | tutti |
| Rete TomTom (flussi, percentili velocità) | ✅ in pipeline | A, C, D |
| Rete PGTU 2026 (classifica funzionale) | ✅ in pipeline | A, C |
| Semafori | ✅ in pipeline | A |
| **Censimento ISTAT per sezione** (socio-demografia) | ✅ disponibile, da agganciare | **B** |
| **Date/geometrie interventi** (Zone 30/velox/strade scolastiche) | ✅ disponibile, da strutturare | **B, C, D** |
| Immagini street-level (Mapillary) | ⏳ future work | E |

Con censimento e date interventi disponibili, **tutti e quattro i moduli attivi
(A–D) sono fattibili**: non ci limitiamo all'MVP ridotto.

Nodo operativo di Fase 0: (1) aggancio geografico del censimento alla rete e
scelta dell'**unità spaziale** (sezione di censimento vs quartiere vs griglia,
con test MAUP); (2) strutturazione della tabella interventi.

---

## 10. Architettura software e impatto sul repo

Nuovi moduli come estensione naturale della pipeline `sNN`, stesso stile e
stesse convenzioni (config-driven, tracciabilità per ID, seed fissato).

```
src/
  s03_spf.py              # esteso: superficie di rischio predittiva
  s07_hin.py              # Modulo A — HIN + NKDE (o esteso in s05)
  s08_equita.py           # Modulo B — indice di bisogno, Gini, LISA, equity zones
  s09_ottimizzazione.py   # Modulo C — MCLP multi-obiettivo rischio+equità
  s04_empirical_bayes.py  # esteso: before-after (Modulo D)
  utils/
    equity_utils.py       # Gini, concentration index, LISA bivariata
    optim_utils.py        # formulazione e solver MCLP / Pareto

dashboard/
  # nuove tab: "Rischio (HIN)", "Equità", "Scenari", "Valutazione"
  # riuso del pattern slider what-if già presente nella tab Sensitività

config.yaml
  # nuove sezioni:
  #   paths.censimento, paths.interventi
  #   equita: {unita_spaziale, pesi_bisogno, percentili}
  #   ottimizzazione: {budget, raggio_influenza, peso_equita, solver}
  #   before_after: {finestra_pre, finestra_post, metodo}

requirements.txt
  # aggiunte: libpysal, esda, mapclassify, pulp (o ortools), pymoo
  # (opzionali future: pysal/spopt, causalimpact)

tests/
  # test_s07_hin.py, test_s08_equita.py, test_s09_ottimizzazione.py
```

Principi invariati: modularità (una funzione = una cosa, testabile),
configurabilità (mai hardcoded), tracciabilità (ogni risultato riconducibile ai
dati grezzi via ID), riproducibilità.

*(La numerazione `s07/s08/s09` è indicativa: HIN può anche confluire in `s05`.)*

---

## 11. Cautele metodologiche trasversali

Da dichiarare esplicitamente nel paper — sono ciò che i revisori cercano.

- **MAUP** — unità spaziale dichiarata e testata su ≥2 scale (tocca B e C).
- **Pesi degli indici** (bisogno, ICP) — analisi di sensibilità sistematica.
- **Underreporting** di pedoni/ciclisti — distorce rischio ed equità dove la
  mobilità attiva è più alta; da segnalare come limite.
- **Ecological fallacy** — no inferenze individuali da dati aggregati.
- **Regression to the mean** — già gestita da EB; centrale anche nel before-after.
- **L'ottimo è supporto, non sostituto** della decisione: validare con esperti.
- **Qualità della geocodifica** — già gestita con i flag in `s00`; da mantenere
  come filtro dichiarato.

---

## 12. Roadmap e sequenza di sviluppo

Ordine per rapporto valore-scientifico/sforzo e coerente con le dipendenze.

| Fase | Contenuto | Deliverable | Dipendenze |
|---|---|---|---|
| **0** | Verifica dati + unità spaziale (MAUP) | notebook + `config.yaml` (paths censimento/interventi) | — |
| **1** | **Modulo B — Equità** (`s08` + tab) | indice bisogno, Gini, LISA, equity zones | Fase 0 |
| **2** | **Modulo A — HIN + NKDE** (`s07`/`s05`) | HIN, hotspot di rete, osservato vs predetto | esistente |
| **3** | **Modulo C — Ottimizzazione** (`s09` + tab) | MCLP multi-obiettivo, frontiera Pareto | Fasi 1–2 |
| **4** | **Modulo D — Before-after** (est. `s04` + tab) | stima EB/ITS per intervento, ≥1 caso reale | dati interventi |
| **5** | **Modulo E — Computer vision** | *future work*, citato nel paper | — |

**Percorsi:**
- MVP conferenza minimo credibile: **Fase 0 → 1 → 3**;
- paper forte: **+ Fase 2**;
- framework completo: **+ Fase 4**, con Fase 5 come future work.

Con **Fase 0 + 1** si ha già un paper autonomo (Equity Dashboard); con
**1 + 3** un paper forte; **1+2+3+4** è la visione completa da presentare come
framework PSS.

---

## 13. Riferimenti bibliografici

**Before-after / valutazione:** Hauer (1997) *Observational Before-After
Studies in Road Safety*; Highway Safety Manual; CMF Clearinghouse; Bernal,
Cummins & Gasparrini (2017, ITS); Brodersen et al. (2015, CausalImpact); Grundy
et al. (2009, BMJ, 20mph zones); Cochrane review speed cameras.

**Equità:** Litman (*Evaluating Transportation Equity*); Lucas (2012, *Transport
and social exclusion*); Karner / Golub / Martens (transport justice);
concentration index (letteratura sanitaria); OECD/Nardo handbook (composite
indicators); PySAL/esda per LISA.

**Rischio / HIN:** FHWA Systemic Safety Project Selection Tool; Vision Zero HIN
(NYC/SF); Okabe & Sugihara (network spatial analysis); Besag-York-Mollié / INLA;
HSM Safety Performance Functions.

**Ottimizzazione:** Church & ReVelle (1974, MCLP); ReVelle & Eiselt (facility
location review); Deb et al. (NSGA-II); pymoo; OR-Tools.

**Computer vision:** Mapillary Vistas; Place Pulse / Streetscore (MIT Media
Lab); segmentazione urbana (Cityscapes, DeepLab).

**Dati Italia:** incidentalità ISTAT-ACI; censimento ISTAT per socio-demografia;
OpenStreetMap per la rete stradale.
