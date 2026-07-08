# Piano di implementazione — "Who Gets Safe Streets?"

> Piano operativo di sviluppo del PSS equity-aware. Traduce `SPECIFICA_PSS.md`
> in **work package, task, firme di funzioni, chiavi di config, test e criteri
> di accettazione**, ancorati al codice esistente (`s00`→`s06` + dashboard).
>
> Titolo del contributo: *"Who Gets Safe Streets? An Open-Source Spatial
> Decision Support System for Equity-Aware Road Safety Planning"*.
>
> Documenti a monte: `APPROFONDIMENTI_RICERCA.md` (ricerca),
> `SPECIFICA_PSS.md` (specifica), `ROADMAP_PSS.md` (sintesi fasi).

---

## 0. Quadro d'insieme

### 0.1 Work package e dipendenze

```
WP0 Dati e fondamenta ──────────────┬──→ WP2 Equità (s08) ────┐
                                    │                          ├──→ WP3 Ottimizzazione (s09)
WP1 HIN + NKDE (s07)  [indipendente]┴──────────────────────────┘
WP0 (tabella interventi) ──────────────→ WP4 Before-after (s10)
WP5 Integrazione + paper  ←─ tutti
```

- **WP1 non dipende da WP0**: usa solo dati già in pipeline → può partire
  subito ed è il "primo commit" a basso rischio.
- **WP2 è il modulo di punta** (cuore del paper): dipende da WP0.
- **WP3** consuma gli output di WP1 (domanda di rischio) e WP2 (equità).
- **WP4** dipende solo dalla tabella interventi (T0.2) e dalla SPF esistente.

### 0.2 Milestone

| Milestone | Contenuto | Valore |
|---|---|---|
| **M1** | WP1 completo (HIN + layer rischio) | primo risultato presentabile |
| **M2** | WP0 + WP2 completi (Equity Dashboard) | **paper minimo pubblicabile** |
| **M3** | + WP3 (ottimizzazione con slider) | paper forte, demo "wow" |
| **M4** | + WP4 (≥1 caso before-after) | framework completo |

### 0.3 Convenzioni (invariate rispetto alla pipeline esistente)

- Ogni step è un modulo `src/sNN_nome.py` con `main(config)` eseguibile via
  `python -m src.sNN_nome`, registrato nell'array `STEPS` di `run_pipeline.sh`.
- Tutti i parametri in `config.yaml` (mai hardcoded); caricamento via
  `src.config.carica_config()`.
- Calcoli geometrici in `EPSG:32633`; export per dashboard in `EPSG:4326`.
- Ogni step produce un `riassumi_*()` loggato + output in `data/interim/` o
  `data/processed/`.
- Test in `tests/test_sNN_*.py` con fixture sintetiche piccole (nessun dato
  reale nel repo).
- La dashboard **non calcola nulla di pesante nei callback**: tutto ciò che è
  oneroso (LISA, frontiera di Pareto, NKDE) viene pre-calcolato nella pipeline;
  i callback filtrano e aggregano soltanto. Fa eccezione il Gini sugli elementi
  filtrati (O(n log n), va bene al volo) — stesso principio del ricalcolo ICP
  già fatto in `_ricalcola_icp_fasce`.

### 0.4 Nuove dipendenze

```txt
# requirements.txt — aggiunte
libpysal>=4.9        # pesi spaziali (WP2)
esda>=2.5            # Moran, LISA bivariata (WP2)
mapclassify>=2.6     # classificazione choropleth (WP2)
pulp>=2.7            # solver ILP per MCLP (WP3)
# opzionali / valutare in corso d'opera:
# pymoo>=0.6         # NSGA-II se ε-constraint non basta (WP3)
# ruptures / statsmodels già presente per ITS (WP4)
```

---

## WP0 — Dati e fondamenta (Fase 0)

*Obiettivo: rendere disponibili e agganciati i due dataset nuovi (censimento
ISTAT, interventi) e decidere l'unità spaziale. Nessuna analisi qui: solo
ingest, validazione, scelte dichiarate.*

### T0.1 — Ingest censimento ISTAT → `src/s0c_censimento.py` (o notebook + step)

1. **Esplorazione** in `notebooks/00_verifica_dati_equita.ipynb`:
   variabili disponibili per sezione di censimento (popolazione, % 0-14,
   % 65+, % stranieri, istruzione, e reddito/deprivazione se disponibile a
   questa scala — altrimenti scala superiore con nota MAUP).
2. **Step pipeline** `s0c_censimento.py`:
   - `carica_sezioni(config) -> gpd.GeoDataFrame` — geometrie sezioni +
     riproiezione a `EPSG:32633`;
   - `carica_variabili_censimento(config) -> pd.DataFrame` — join su codice
     sezione;
   - `valida_censimento(gdf) -> dict` — copertura spaziale vs rete, sezioni
     senza popolazione, valori mancanti;
   - `salva(gdf, percorso)` → `data/interim/censimento_prep.gpkg`.

```yaml
# config.yaml — aggiunta
paths:
  raw:
    censimento_sezioni: "data/raw/censimento/sezioni_roma.gpkg"   # o shp ISTAT
    censimento_dati: "data/raw/censimento/indicatori_sezioni.csv"
  interim:
    censimento_prep: "data/interim/censimento_prep.gpkg"
```

**DoD:** GeoPackage con geometrie valide, indicatori per sezione, report di
copertura loggato; test su fixture di 5 sezioni sintetiche.

### T0.2 — Tabella interventi → `src/s0d_interventi.py`

Schema minimo (vincolante per WP2/WP3/WP4):

| Campo | Tipo | Note |
|---|---|---|
| `id_intervento` | str | univoco |
| `tipo` | categorico | `zona30`, `velox`, `strada_scolastica`, `attraversamento`, `altro` |
| `data_inizio` | date | inizio lavori/attivazione — **cruciale per WP4** |
| `data_fine` | date/null | null se puntuale o in corso |
| `fase` | categorico | `pianificato`, `in_corso`, `realizzato` |
| `geometria` | Point/Polygon/LineString | come da fonte |
| `raggio_influenza_m` | float/null | override del default per tipo |

Funzioni: `carica_interventi(config)`, `valida_interventi(gdf)` (date parse,
geometrie valide, tipi noti), `salva(...)` →
`data/interim/interventi_prep.gpkg`.

```yaml
paths:
  raw:
    interventi: "data/raw/interventi.gpkg"   # o CSV+coords, adattare loader
  interim:
    interventi_prep: "data/interim/interventi_prep.gpkg"

interventi:
  raggio_influenza_default_m:
    zona30: 0            # ha già estensione poligonale
    velox: 500
    strada_scolastica: 300
    attraversamento: 150
```

**DoD:** tutti gli interventi caricati con data e tipo validi; conteggio per
tipo/fase loggato; test loader.

### T0.3 — Unità spaziale di analisi + MAUP

- Default: **sezione di censimento** (massima risoluzione).
- Aggregazione alternativa per sensibilità: **griglia esagonale ~500 m** (H3 o
  esagoni shapely) e/o zone urbanistiche.
- Utility condivisa `src/utils/spatial_units.py`:
  - `costruisci_unita(config, scala) -> gpd.GeoDataFrame`
  - `aggrega_a_unita(gdf_punti_o_linee, unita, colonne, metodo) -> pd.DataFrame`
    (usata da WP2 per aggregare excess_EPDO, interventi, popolazione).

```yaml
equita:
  unita_spaziale: "sezione"        # "sezione" | "griglia" | "zone"
  griglia_lato_m: 500              # per la scala di sensibilità
```

**DoD:** la stessa analisi WP2 gira su ≥2 scale cambiando una sola chiave di
config (requisito MAUP per il paper).

---

## WP1 — Modulo A: HIN + NKDE → `src/s07_hin.py`

*Input: `priorita_finale.gpkg`, `incidenti_matched.gpkg`, `segmenti.gpkg`.
Nessuna dipendenza da WP0.*

### T1.1 — High Injury Network

```python
def calcola_ksi_km(segmenti: gpd.GeoDataFrame,
                   incidenti: gpd.GeoDataFrame,
                   usa_eb: bool = True) -> pd.Series:
    """KSI/km per segmento. Se usa_eb, pesa con la stima EB (più stabile
    della conta grezza: eventi rari). KSI = mortali + feriti (il dato non
    distingue gravi/lievi — dichiararlo)."""

def costruisci_hin(segmenti: gpd.GeoDataFrame,
                   ksi_km: pd.Series,
                   soglia_copertura: float = 0.70) -> pd.Series:
    """Flag is_hin: ranking decrescente per KSI/km, cumula i KSI finché
    la copertura raggiunge la soglia. Ritorna anche la % di rete usata."""

def curva_concentrazione(segmenti, ksi_km) -> pd.DataFrame:
    """Curva % rete vs % KSI (per il grafico 'il 15% della rete contiene
    il 70% dei feriti gravi') — è anche una figura chiave del paper."""
```

```yaml
hin:
  soglia_copertura: 0.70     # quota di KSI da coprire
  usa_eb: true
  metrica: "ksi"             # "ksi" | "epdo"
```

### T1.2 — NKDE (hotspot di rete)

Implementazione pragmatica (evitare dipendenze pesanti):
1. **Lixelizzazione**: spezzare i segmenti in lixel da ~20 m
   (`shapely.segmentize` + split);
2. per ogni lixel, somma kernel (quartico/gaussiano, bandwidth configurabile,
   default 200 m) sulle **distanze di rete** verso gli incidenti — le distanze
   di rete si calcolano sul grafo già costruito in `s02` (riusare
   `_costruisci_indice_archi`); in prima battuta è accettabile l'approssimazione
   "distanza lungo lo stesso segmento + adiacenti entro 1 hop", dichiarata;
3. output: colonna `nkde` per lixel → `data/processed/nkde.gpkg`.

```yaml
nkde:
  lunghezza_lixel_m: 20
  bandwidth_m: 200
  kernel: "quartico"
```

*Nota: se i tempi di calcolo su ~94k archi esplodono, fallback dichiarato =
KDE euclideo mascherato sulla rete (meno corretto, da segnalare come limite).*

### T1.3 — Layer osservato vs predetto

Semplice riorganizzazione di dati già esistenti: export per segmento di
`E_i` (SPF, rischio *predetto*), `EB_i` e `O_i` (rischio *osservato-corretto*)
come layer distinti in `s06_export`, con una colonna `gap_pred_oss = EB_i − E_i`
(già `excess_i`). La novità è la **presentazione**, non il calcolo.

### T1.4 — Dashboard

Nuovi layer nella tab **Mappa** esistente (non serve una tab nuova):
- toggle "HIN" (segmenti `is_hin` evidenziati);
- metrica mappa aggiuntiva nel `filtro-metrica` esistente: `nkde`,
  `rischio_predetto (E_i)`.

**DoD WP1:** `s07_hin.py` in `run_pipeline.sh`; `priorita_finale` arricchito di
`ksi_km`, `is_hin`, `rank_ksi`; `nkde.gpkg` prodotto; curva di concentrazione
esportata in `reports/`; toggle funzionanti; test su rete sintetica a 10
segmenti con HIN atteso noto.

---

## WP2 — Modulo B: Equità → `src/s08_equita.py` + `src/utils/equity_utils.py`

*Il cuore del paper. Input: `censimento_prep`, `interventi_prep`,
`priorita_finale` (excess_EPDO), unità spaziali (T0.3).*

### T2.1 — Vulnerabilità sociale per unità

```python
def calcola_vulnerabilita_sociale(unita: gpd.GeoDataFrame,
                                  config: dict) -> pd.Series:
    """Composite index 0-100: combina %0-14, %65+, %stranieri,
    istruzione, (reddito/deprivazione se disponibile).
    Normalizzazione: riusa s05.normalizza_robusta (P1-P99).
    Aggregazione: media pesata con pesi da config."""
```

```yaml
equita:
  pesi_vulnerabilita:
    perc_bambini: 0.25
    perc_anziani: 0.25
    perc_stranieri: 0.20
    istruzione_bassa: 0.30
  # analisi di sensibilità: lista di schemi alternativi di pesi
  schemi_sensibilita: ["equi", "focus_eta", "focus_deprivazione"]
```

### T2.2 — Dotazione di interventi per unità

```python
def calcola_dotazione(unita, interventi, config) -> pd.DataFrame:
    """Per unità e per tipo: conteggio interventi (con buffer
    raggio_influenza per i puntuali, overlay per zone30 poligonali),
    normalizzato per popolazione e per km di rete."""
```

Decisione dichiarata: un velox "serve" un'unità se il suo buffer di influenza
la interseca (coverage), non solo se vi ricade il punto.

### T2.3 — Indice di bisogno

```python
def calcola_bisogno(vuln: pd.Series, rischio: pd.Series,
                    metodo: str = "geometrica") -> pd.Series:
    """bisogno = combinazione di vulnerabilità sociale e rischio
    aggregato all'unità (excess_EPDO dei siti che vi ricadono,
    via spatial_units.aggrega_a_unita).
    metodo: "geometrica" (default: penalizza gli squilibri) | "pesata"."""
```

### T2.4 — Misure di iniquità → `equity_utils.py`

```python
def gini(dotazione: np.ndarray, peso_pop: np.ndarray) -> float:
    """Gini pesato per popolazione sulla dotazione pro-capite."""

def curva_lorenz(dotazione, peso_pop) -> pd.DataFrame: ...

def concentration_index(dotazione: np.ndarray,
                        bisogno: np.ndarray,
                        peso_pop: np.ndarray) -> float:
    """CI = 2·cov(dotazione, rank_frazionale(bisogno)) / media(dotazione).
    CI < 0: interventi concentrati sulle unità a basso bisogno (iniquo
    in senso verticale). È LA statistica-titolo del paper."""

def lisa_bivariata(unita: gpd.GeoDataFrame,
                   x: str, y: str,
                   k_vicini: int = 8,
                   seed: int = 42) -> pd.DataFrame:
    """Moran_Local_BV (esda) su bisogno (x) vs dotazione (y), pesi KNN
    o queen contiguity (libpysal). Ritorna quadrante e p-value per unità.
    Quadrante High-Low (alto bisogno, bassa dotazione) = mismatch."""
```

### T2.5 — Equity priority zones + choropleth bivariata

```python
def classifica_bivariata(bisogno, dotazione, n_classi=3) -> pd.Series:
    """Classi 3×3 (terzili bisogno × terzili dotazione) per la
    choropleth bivariata. Palette dedicata in dashboard."""

def equity_priority_zones(df, lisa, p_max=0.05) -> pd.Series:
    """Flag: (terzile bisogno alto & terzile dotazione basso) OPPURE
    cluster LISA High-Low significativo."""
```

Output step: `data/processed/equita.gpkg` (per unità: vulnerabilità, rischio
aggregato, bisogno, dotazione per tipo, classe bivariata, quadrante LISA,
`equity_priority`) + `data/processed/equita_indici.json` (Gini, CI, Moran I
globale — per scala e per schema di pesi → tabella di sensibilità del paper).

### T2.6 — Dashboard: tab "Equità"

Nuova `dcc.Tab(label="Equità", value="equita")` nel blocco tab esistente
(`layouts.py:628`), callback in `registra_callbacks`:
- **controlli**: dropdown tipo intervento (o tutti), dropdown strato
  socio-demografico, radio unità spaziale (se pre-calcolate entrambe le scale);
- **mappa**: choropleth bivariata 3×3 + overlay cluster LISA High-Low +
  contorno equity priority zones;
- **pannello indici**: Gini e concentration index **ricalcolati al volo sugli
  elementi filtrati** (leggeri) + curva di Lorenz;
- **pannello sensibilità**: tabella Gini/CI per schema di pesi e scala (da
  `equita_indici.json`, pre-calcolata).

**DoD WP2:** pipeline `s08` end-to-end su ≥2 scale; indici coerenti su fixture
sintetiche con valori noti (es. dotazione uniforme → Gini≈0; dotazione tutta
nell'unità meno bisognosa → CI fortemente negativo); tab funzionante; figure
del paper esportabili (choropleth, Lorenz, tabella sensibilità). **Questa è la
milestone M2 = paper minimo.**

---

## WP3 — Modulo C: Ottimizzazione → `src/s09_ottimizzazione.py` + `src/utils/optim_utils.py`

*Input: domanda di rischio (WP1/s05), equity priority (WP2). Dipende da M1+M2.*

### T3.1 — Domanda e siti candidati

```python
def costruisci_domanda(priorita: gpd.GeoDataFrame,
                       equita: gpd.GeoDataFrame,
                       peso_equita: float) -> pd.DataFrame:
    """Punti di domanda = siti (segmenti/intersezioni) con
    d_i = (1-w)·norm(excess_EPDO_i) + w·norm(bisogno_unita(i)).
    w = peso_equita ∈ [0,1] (lo slider)."""

def costruisci_candidati(priorita, tipo_intervento, config) -> gpd.GeoDataFrame:
    """Siti candidati per tipo (es. velox: segmenti con ratio_v85_limite
    alto; attraversamenti: intersezioni non semaforizzate; ...).
    Regole per tipo in config."""

def matrice_copertura(candidati, domanda, raggio_m) -> "scipy.sparse":
    """a_ij = 1 se il candidato j copre il punto di domanda i
    (distanza ≤ raggio). Sparse: cKDTree per i vicini."""
```

### T3.2 — MCLP (PuLP)

Formulazione (Church & ReVelle 1974), in `optim_utils.py`:

```
max  Σ_i d_i · y_i
s.t. y_i ≤ Σ_{j ∈ N_i} x_j      ∀i      (coperto solo se un candidato vicino è scelto)
     Σ_j x_j ≤ p                         (budget: numero di interventi)
     x_j, y_i ∈ {0,1}
```

```python
def risolvi_mclp(domanda, copertura, p, solver="PULP_CBC_CMD",
                 timeout_s=120) -> dict:
    """Ritorna candidati scelti, domanda coperta, gap, tempo.
    Su istanze grandi: pre-filtro dei candidati dominati +
    aggregazione della domanda per unità."""
```

### T3.3 — Multi-obiettivo e frontiera di Pareto

Approccio a due livelli (semplice prima, sofisticato poi):
1. **Weighted-sum via slider** (T3.1): un solo run per il valore di `w`
   scelto — è l'interazione principale della dashboard;
2. **Frontiera pre-calcolata**: `frontiera_pareto(p, n_punti=11)` risolve
   l'MCLP per `w ∈ {0, 0.1, …, 1}` nella pipeline e salva i punti
   (rischio coperto, equità coperta, siti scelti) →
   `data/processed/scenari.parquet`. La dashboard *mostra* la frontiera e i
   3 scenari nominati ("efficienza pura" w=0, "bilanciato" w=0.5,
   "equità pura" w=1) senza risolvere nulla al volo;
3. *(estensione, solo se serve per il paper)*: ε-constraint o NSGA-II (pymoo)
   per una frontiera vera non-dominata — la weighted-sum è una scalarizzazione
   e va dichiarata come tale.

```yaml
ottimizzazione:
  budget_default: 20            # numero interventi
  raggio_copertura_m: 500
  peso_equita_default: 0.5
  n_punti_frontiera: 11
  solver: "PULP_CBC_CMD"
  timeout_s: 120
```

### T3.4 — Dashboard: tab "Scenari"

- controlli: budget (slider p), tipo intervento, raggio, **slider
  efficienza↔equità**;
- mappa: siti proposti per lo scenario corrente (marker), equity zones sotto;
- grafico frontiera di Pareto (rischio coperto vs equità coperta) con il punto
  corrente evidenziato;
- confronto side-by-side dei 3 scenari nominati (small multiples).
- Interazione: lo slider seleziona il punto **pre-calcolato** più vicino
  (nessun solve nel callback). Un pulsante "ricalcola scenario esatto" può
  lanciare un solve on-demand con timeout, in seconda battuta.

**DoD WP3:** su istanza sintetica 20 candidati / 100 domande l'MCLP trova
l'ottimo noto; frontiera monotona (rischio ↓ quando equità ↑); scenari
riproducibili (seed); tab funzionante con < 1 s di latenza percepita; tempi di
solve su Roma documentati (limite computazionale da dichiarare).

---

## WP4 — Modulo D: Before-after → `src/s10_valutazione.py`

*Input: `interventi_prep` (T0.2), SPF (`s03`), incidenti con date (`s00`).
Riusa la macchina EB di `s04`.*

### T4.1 — Associazione interventi ↔ siti e finestre temporali

```python
def siti_trattati(interventi, segmenti, intersezioni, config) -> pd.DataFrame:
    """Per intervento: siti nel raggio/perimetro di influenza,
    finestra 'prima' [data_inizio − n_anni_pre, data_inizio) e
    'dopo' (data_fine, data_fine + n_anni_post]. Esclude il periodo
    lavori. Interventi troppo recenti (dopo < 12 mesi) → flag
    'immaturo', esclusi dalla stima ma mostrati in dashboard."""
```

### T4.2 — EB before-after (Hauer)

```python
def eb_before_after(o_prima, o_dopo, e_prima, e_dopo, k) -> dict:
    """Standard Hauer:
    EB_prima = w·E_prima + (1−w)·O_prima,  w = 1/(1+k·E_prima)
    π = EB_prima · (E_dopo/E_prima)        # atteso 'dopo' senza intervento
    θ = (O_dopo/π) / (1 + Var(π)/π²)       # indice di efficacia (CMF)
    Var(θ), IC 95%. θ<1 = riduzione attribuibile all'intervento."""
```

Le SPF per E_prima/E_dopo sono quelle già calibrate in `s03` (stesso `k`).

### T4.3 — Gruppo di controllo

```python
def seleziona_controlli(sito, pool, n=20) -> pd.DataFrame:
    """Matching su: stessa categoria funzionale, TGM in ±30%,
    nessun intervento nel periodo, distanza > 2·raggio_influenza
    (no contaminazione/spillover). Odds ratio col comparison group
    come check di robustezza dell'EB."""
```

### T4.4 — ITS sul caso di punta

Per **≥1 caso reale** (una Zona 30 con storia sufficiente): serie mensile di
incidenti nell'area trattata, regressione segmentata
(`statsmodels`: livello + trend, dummy post, controllo stagionalità e trend
cittadino come covariata) → grafico serie + controfattuale con banda.
CausalImpact come estensione opzionale, non vincolante per M4.

```yaml
before_after:
  n_anni_pre: 3
  n_anni_post: 2
  mesi_minimi_post: 12
  n_controlli: 20
  tolleranza_tgm: 0.30
```

### T4.5 — Dashboard: tab "Valutazione"

- layer interventi sulla mappa (icona per tipo, colore per fase);
- click su intervento → pannello: θ con IC (gauge/forest plot), O vs π,
  serie temporale prima/dopo con banda, confronto col gruppo di controllo,
  badge "immaturo" dove i dati non bastano;
- vista aggregata: forest plot dei θ per tipo di intervento (meta-vista:
  "le zone 30 di Roma stanno funzionando?").

**DoD WP4:** θ e IC corretti su fixture con valori noti (caso costruito a
mano); ≥1 caso reale con ITS ed EB concordi in segno; tab funzionante;
`data/processed/valutazioni.parquet` prodotto.

---

## WP5 — Integrazione, qualità, materiale per il paper

1. **Orchestratore**: aggiungere a `run_pipeline.sh` →
   `s0c_censimento`, `s0d_interventi`, `s07_hin`, `s08_equita`,
   `s09_ottimizzazione`, `s10_valutazione` (con flag per saltare gli step i
   cui input mancano, così la pipeline base resta eseguibile).
2. **`s06_export` esteso**: GeoJSON dei nuovi layer, figure statiche del paper
   (curva concentrazione HIN, choropleth bivariata, Lorenz, frontiera Pareto,
   forest plot) in `reports/paper/` a 300 dpi.
3. **Test e CI**: ogni WP porta i suoi test; obiettivo: `pytest -q` verde
   senza dati reali (tutte fixture sintetiche).
4. **Documentazione**: README aggiornato (sezione "moduli PSS"), docstring
   coerenti con lo stile esistente, `notebooks/` con un notebook di
   walkthrough per modulo.
5. **Riproducibilità per il paper**: tag di release, archivio del codice
   (es. Zenodo/DOI) al momento della submission; `random_seed` rispettato in
   LISA (permutazioni) e in ogni componente stocastica.

---

## Ordine di esecuzione consigliato (sequenza dei PR)

| # | PR | Contenuto | Sblocca |
|---|---|---|---|
| 1 | `feat(hin)` | WP1 completo (s07 + layer mappa) | M1 |
| 2 | `feat(dati-equita)` | T0.1 + T0.2 + T0.3 (ingest + unità spaziali) | WP2, WP4 |
| 3 | `feat(equita-core)` | T2.1→T2.5 (s08 + equity_utils + test) | — |
| 4 | `feat(equita-dashboard)` | T2.6 (tab Equità) | **M2 — paper minimo** |
| 5 | `feat(ottimizzazione-core)` | T3.1→T3.3 (s09 + optim_utils + frontiera) | — |
| 6 | `feat(scenari-dashboard)` | T3.4 (tab Scenari) | **M3 — paper forte** |
| 7 | `feat(before-after)` | WP4 (s10 + tab Valutazione) | **M4** |
| 8 | `chore(paper)` | WP5 (export figure, docs, release) | submission |

Ogni PR: pipeline eseguibile end-to-end, test verdi, un paragrafo di
motivazione metodologica nel body (diventa materiale per il paper).

---

## Rischi implementativi e mitigazioni

| Rischio | Impatto | Mitigazione |
|---|---|---|
| Reddito non disponibile a scala di sezione | indice vulnerabilità più povero | usare istruzione+età+stranieri; reddito a scala superiore con nota MAUP |
| NKDE lento su 94k archi | WP1 ritarda | lixel 20m + bandwidth locale; fallback KDE euclideo mascherato, dichiarato |
| MCLP intrattabile su tutta Roma | WP3 ritarda | aggregare domanda per unità; pre-filtrare candidati; CBC→HiGHS se serve |
| Pochi interventi "maturi" per il before-after | WP4 debole | concentrarsi su 1 caso solido (Zona 30) + flag 'immaturo' per gli altri |
| LISA instabile su unità con pop≈0 | falsi cluster | filtro popolazione minima + pesi KNN invece di contiguity |
| Slider "in tempo reale" troppo lento | demo scadente | frontiera pre-calcolata (T3.3), mai solve nel callback |

---

## Definition of Done complessiva (pronto per la conferenza)

- [ ] `bash run_pipeline.sh` esegue s00→s10 senza errori sui dati di Roma;
- [ ] dashboard con le tab nuove (Equità, Scenari, Valutazione) + layer HIN;
- [ ] concentration index e Gini calcolati su ≥2 scale e ≥3 schemi di pesi
      (tabella di sensibilità);
- [ ] frontiera efficienza↔equità con ≥11 punti e 3 scenari nominati;
- [ ] ≥1 valutazione before-after completa (EB + ITS) su un intervento reale;
- [ ] tutte le figure del paper riproducibili da `reports/paper/`;
- [ ] `pytest -q` verde; release taggata.
