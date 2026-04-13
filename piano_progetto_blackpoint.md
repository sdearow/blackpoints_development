# Piano di Progetto: Sistema di Identificazione dei Black Point Incidentali di Roma

## Contesto e obiettivo

Realizzazione di un sistema integrato per l'identificazione, la classificazione e la visualizzazione dei siti ad alta concentrazione incidentale (black spot e black section) sulla rete stradale di Roma Capitale, basato sulla metodologia Empirical Bayes con indice composito di priorità.

### Dati disponibili in input
- **Database incidenti**: dal 2010, geolocalizzati (buona qualità fino a maggio 2022, da ri-geolocalizzare dal maggio 2022 in poi). Campi: coordinate, gravità (morti/feriti gravi/feriti lievi/soli danni), tipo veicoli coinvolti, condizioni meteo, tipologia incidente, note.
- **Dati TomTom**: flussi campionari espansi giornalieri e percentili di velocità per archetto, su tutta la rete principale e secondaria.
- **Rete PGTU**: classificazione funzionale delle strade (Scorrimento, Interquartiere, Quartiere, Interzonale, Locale, Extraurbana).
- **Database semafori**: localizzazione delle intersezioni semaforizzate.

### Stack tecnologico raccomandato
- **Linguaggio**: Python 3.11+
- **GIS**: GeoPandas, Shapely, PostGIS (opzionale per grandi volumi)
- **Statistica**: statsmodels (GLM binomiale negativa), scipy
- **Visualizzazione/Dashboard**: Leaflet.js o Mapbox GL JS per la mappa, React per l'interfaccia, oppure un framework Python come Dash/Streamlit per un prototipo rapido
- **Database**: GeoPackage per le fasi di analisi, PostgreSQL/PostGIS per la produzione

---

## FASE 0 — Preparazione e pulizia dei dati

### Obiettivo
Portare tutti i dataset in un formato coerente, pulito e pronto per il matching.

### Task 0.1 — Importazione e pulizia del database incidenti

**Input**: file originale degli incidenti (CSV, XLSX, o database)

**Operazioni**:
1. Importare il dataset completo e ispezionare la struttura (colonne, tipi, valori mancanti)
2. Standardizzare i campi:
   - Coordinate: verificare sistema di riferimento (EPSG:4326 WGS84 o EPSG:32633 UTM33N), convertire tutto a un CRS unico (consiglio UTM33N per i calcoli metrici, WGS84 per la visualizzazione finale)
   - Gravità: creare un campo categorico standardizzato con valori `mortale`, `ferito_grave`, `ferito_lieve`, `solo_danni`
   - Data/ora: parsare in formato datetime, estrarre anno, mese, giorno della settimana, fascia oraria
   - Tipo veicoli: standardizzare in categorie (`auto`, `moto`, `bicicletta`, `pedone`, `mezzo_pesante`, `altro`)
   - Via/strada: normalizzare i nomi (maiuscole, abbreviazioni: "V." → "Via", "P.le" → "Piazzale", etc.)
3. Filtrare le annualità:
   - **Dataset principale**: annualità complete con buona geocodifica (es. 2017-2021, 5 anni)
   - **Dataset esteso**: tutte le annualità 2010-2021 (per analisi di sensibilità)
   - **Dataset futuro**: placeholder per i dati 2022+ quando saranno ri-geolocalizzati
4. Flag di qualità della geocodifica:
   - Per ogni incidente, calcolare un indicatore di affidabilità della posizione (es. `alta` se ha numero civico specifico, `media` se ha solo il nome della strada, `bassa` se ha indicazioni vaghe)
   - Per i dati post-maggio 2022: flaggare come `da_rigeolocalizzare`

**Output**: GeoDataFrame `incidenti_clean` con geometria Point, tutti i campi standardizzati, e flag di qualità.

**Validazione**:
- Conteggio incidenti per anno (verificare continuità temporale)
- Distribuzione spaziale (heatmap grezzo per verificare che non ci siano cluster anomali da errori di geocodifica)
- Distribuzione per gravità (verificare coerenza con dati ISTAT Roma)

### Task 0.2 — Importazione e preparazione della rete TomTom

**Input**: shapefile o GeoJSON della rete TomTom con attributi di flusso e velocità

**Operazioni**:
1. Importare la rete come GeoDataFrame con geometria LineString
2. Verificare topologia: connessione del grafo, archi duplicati, archi a lunghezza zero
3. Per ogni archetto, calcolare:
   - `lunghezza_m`: lunghezza in metri
   - `TGM_anno`: traffico giornaliero medio annuo (media dei flussi giornalieri disponibili, pesata per rappresentatività stagionale se possibile)
   - `V_media`: velocità media di tutti i veicoli
   - `V85`: 85° percentile delle velocità
   - `V15`: 15° percentile delle velocità
   - `V75`: 75° percentile
   - `V25`: 25° percentile
   - `IQR_norm`: range interquartile normalizzato = (V75 - V25) / V_media
   - `ratio_V85_limite`: rapporto V85 / limite di velocità (se il limite è disponibile nella rete TomTom o derivabile dalla classificazione PGTU)
4. Gestire eventuali archetti con flussi nulli o anomali (soglia minima, interpolazione dai vicini, o esclusione con flag)

**Output**: GeoDataFrame `rete_tomtom` con geometria LineString e tutti gli indicatori calcolati.

### Task 0.3 — Importazione della rete PGTU e dei semafori

**Input**: shapefile della classificazione funzionale PGTU, shapefile/tabella dei semafori

**Operazioni**:
1. Importare la rete PGTU con il campo di classificazione funzionale
2. Importare la localizzazione dei semafori come punti
3. Preparare il join spaziale tra rete TomTom e classificazione PGTU (ogni archetto TomTom riceve la categoria funzionale della strada PGTU su cui giace)

**Output**: campo `categoria_funzionale` aggiunto a `rete_tomtom`, GeoDataFrame `semafori` con geometria Point.

---

## FASE 1 — Matching spaziale: incidenti ↔ rete

### Obiettivo
Assegnare ogni incidente a un elemento della rete (intersezione o segmento) con un criterio rigoroso e tracciabile.

### Task 1.1 — Definizione delle intersezioni

**Operazioni**:
1. Estrarre i nodi della rete TomTom dove convergono 3+ archi (sono le intersezioni)
2. Per ogni nodo-intersezione:
   - Assegnare un ID univoco
   - Classificare il tipo: `semaforizzata` (se un semaforo cade entro 20m dal nodo) o `non_semaforizzata`
   - Contare il numero di bracci
   - Calcolare il flusso entrante totale: somma dei TGM degli archi entranti / 2
   - Definire l'area di influenza: buffer circolare di raggio R (default: 20 metri, parametro configurabile)
3. Opzionale: classificare ulteriormente in `rotatoria` se la geometria lo suggerisce (archi curvi che formano un anello)

**Output**: GeoDataFrame `intersezioni` con geometria Point, buffer, tipo, flusso entrante.

### Task 1.2 — Definizione dei segmenti omogenei

**Operazioni**:
1. Partendo dalla rete TomTom, aggregare gli archetti consecutivi che:
   - Hanno la stessa categoria funzionale PGTU
   - Non sono interrotti da un'intersezione significativa (nodo con 3+ bracci)
   - Hanno TGM simile (variazione < 30% rispetto alla media del segmento — soglia configurabile)
2. Per ogni segmento omogeneo risultante:
   - Assegnare un ID univoco
   - Calcolare la lunghezza totale (somma delle lunghezze degli archetti componenti)
   - Calcolare il TGM come media pesata per lunghezza dei TGM degli archetti
   - Calcolare gli indicatori di velocità come medie pesate per lunghezza
   - Registrare la categoria funzionale
   - Escludere la porzione coperta dai buffer delle intersezioni (ritaglio geometrico)
3. Filtro di lunghezza: segmenti < 100m vengono accorpati al segmento adiacente più simile; segmenti > 2km vengono suddivisi in sotto-segmenti di lunghezza ≈ 1km

**Output**: GeoDataFrame `segmenti` con geometria LineString, tutti gli attributi calcolati.

### Task 1.3 — Assegnazione degli incidenti

**Operazioni**:
1. Per ogni incidente nel dataset pulito:
   - **Step 1**: verificare se cade entro il buffer di un'intersezione → se sì, assegnare all'intersezione
   - **Step 2**: se non cade in nessun buffer intersezione, calcolare la distanza dal segmento più vicino
     - Se distanza < 50m: assegnare al segmento (snap-to-network)
     - Se distanza 50-100m E il nome della strada corrisponde (fuzzy match): assegnare al segmento con flag `match_toponomastico`
     - Se distanza > 100m O nessuna corrispondenza toponomastica: flaggare come `non_assegnato`
   - **Step 3**: per gli incidenti con strade parallele vicine (distanza < 30m da due segmenti diversi), usare il nome della strada come discriminante
2. Generare un report di matching:
   - % incidenti assegnati a intersezioni
   - % incidenti assegnati a segmenti
   - % incidenti non assegnati (con distribuzione spaziale — dove sono? È un cluster che indica un problema di rete?)
   - Distribuzione delle distanze di snap

**Output**: Tabella `incidenti_matched` con campi `tipo_sito` (intersezione/segmento), `id_sito`, `distanza_snap`, `metodo_match`, `flag_qualità`.

**Parametri configurabili** (per analisi di sensibilità):
- `RAGGIO_INTERSEZIONE`: default 20m
- `SOGLIA_SNAP_GEOMETRICA`: default 50m
- `SOGLIA_SNAP_TOPONOMASTICA`: default 100m
- `SOGLIA_VARIAZIONE_TGM_SEGMENTO`: default 0.3
- `LUNGHEZZA_MIN_SEGMENTO`: default 100m
- `LUNGHEZZA_MAX_SEGMENTO`: default 2000m

---

## FASE 2 — Calibrazione delle Safety Performance Functions (SPF)

### Obiettivo
Stimare la relazione statistica tra volume di traffico (e altre variabili) e numero atteso di incidenti per tipologia di sito.

### Task 2.1 — Preparazione del dataset per la regressione

**Operazioni**:
1. Per ogni segmento: creare una riga con:
   - `n_incidenti`: conteggio incidenti nel periodo
   - `n_incidenti_gravi`: conteggio incidenti mortali + feriti gravi
   - `lunghezza_km`: lunghezza del segmento in km
   - `TGM`: traffico giornaliero medio
   - `log_TGM`: logaritmo naturale del TGM
   - `log_L`: logaritmo naturale della lunghezza
   - `categoria_funzionale`: variabile categorica
   - `V_media`, `V85`, `IQR_norm`: indicatori di velocità
   - `n_anni`: numero di anni del periodo di analisi
2. Per ogni intersezione: creare una riga con:
   - `n_incidenti`: conteggio incidenti nel buffer
   - `flusso_entrante`: flusso totale entrante
   - `n_bracci`: numero di bracci
   - `tipo`: semaforizzata / non semaforizzata
   - `n_anni`: numero di anni
3. Escludere siti con TGM = 0 o dati anomali
4. Analisi esplorativa: scatter plot incidenti vs TGM per ciascuna categoria, istogrammi delle distribuzioni

**Output**: DataFrame `df_segmenti_spf` e `df_intersezioni_spf`.

### Task 2.2 — Calibrazione dei modelli SPF

**Operazioni** (da ripetere per ciascuna categoria):

**Per i segmenti** (una SPF per categoria funzionale, o raggruppate se i campioni sono troppo piccoli):

1. Modello base — regressione binomiale negativa:
   ```
   Y ~ NB(μ, k)
   log(μ) = β₀ + β₁·log(TGM) + β₂·log(L) + offset(log(n_anni))
   ```
   L'offset su `log(n_anni)` normalizza per la durata del periodo di osservazione.

2. Verificare:
   - Segno dei coefficienti (β₁ e β₂ devono essere positivi)
   - Significatività (p-value < 0.05)
   - Parametro di sovradispersione k (deve essere > 0; se k → 0 il modello collassa verso la Poisson e l'EB perde potenza)

3. Modello esteso — aggiungere covariate una alla volta:
   ```
   log(μ) = β₀ + β₁·log(TGM) + β₂·log(L) + β₃·V85 + β₄·IQR_norm + offset(log(n_anni))
   ```
   Confrontare AIC/BIC col modello base. Tenere la covariata solo se migliora il fit.

4. Diagnostica:
   - Residui di Pearson vs valori fittati
   - CURE plot: residui cumulati vs TGM e vs lunghezza
   - Test di Freeman-Tukey per la bontà di adattamento

**Per le intersezioni** (una SPF per tipo semaforizzata/non semaforizzata):

1. Modello base:
   ```
   Y ~ NB(μ, k)
   log(μ) = β₀ + β₁·log(flusso_entrante) + offset(log(n_anni))
   ```

2. Modello esteso:
   ```
   log(μ) = β₀ + β₁·log(flusso_entrante) + β₂·n_bracci + offset(log(n_anni))
   ```

3. Stessa diagnostica dei segmenti.

**Output**:
- Oggetto/dizionario `spf_models` con i coefficienti calibrati (β₀, β₁, β₂, ...) e il parametro k per ciascuna categoria
- Report diagnostico con CURE plot e test di bontà di adattamento
- Il valore predetto E(Yᵢ) per ciascun sito

### Task 2.3 — Gestione dei campioni piccoli

Se una categoria funzionale ha troppo pochi siti per una calibrazione stabile (indicativamente < 50-100 siti), avete due opzioni:
1. Accorpare categorie affini (es. Scorrimento + Interquartiere)
2. Usare un modello unico con la categoria funzionale come covariata dummy

Documentare la scelta e verificare che il modello accorpato non introduca bias.

---

## FASE 3 — Calcolo Empirical Bayes e ranking

### Obiettivo
Calcolare la stima EB della frequenza attesa di incidenti per ciascun sito e derivare l'eccesso atteso.

### Task 3.1 — Calcolo EB

**Operazioni**:
Per ogni sito i:

1. Recuperare:
   - `E_i`: valore predetto dalla SPF (dal Task 2.2)
   - `O_i`: incidenti osservati
   - `k`: parametro di sovradispersione del modello SPF applicabile

2. Calcolare il peso EB:
   ```
   w_i = 1 / (1 + E_i * k)
   ```

3. Calcolare la stima EB:
   ```
   EB_i = w_i * E_i + (1 - w_i) * O_i
   ```

4. Calcolare l'eccesso atteso:
   ```
   excess_i = EB_i - E_i
   ```

5. Calcolare la varianza della stima EB (per intervalli di confidenza):
   ```
   Var(EB_i) = EB_i * (1 - w_i)
   ```

**Output**: Tabella `eb_results` con colonne `id_sito`, `tipo_sito`, `O_i`, `E_i`, `w_i`, `EB_i`, `excess_i`, `var_EB_i`.

### Task 3.2 — Pesatura per gravità (EPDO)

**Operazioni**:
1. Definire i pesi EPDO basati sui costi sociali MEF/ISTAT:
   ```python
   PESI_EPDO = {
       'mortale': 167,      # 1.500.000 / 9.000 ≈ 167
       'ferito_grave': 24,  # 220.000 / 9.000 ≈ 24
       'ferito_lieve': 2,   # 17.000 / 9.000 ≈ 2
       'solo_danni': 1      # riferimento
   }
   ```

2. Per ogni sito, calcolare il conteggio EPDO:
   ```
   EPDO_i = Σ (n_incidenti_per_gravità × peso_gravità)
   ```

3. Calcolare l'eccesso pesato:
   ```
   excess_EPDO_i = excess_i × (EPDO_i / O_i)
   ```
   Dove `EPDO_i / O_i` è il peso medio per incidente del sito.

4. Opzionale: convertire in costo sociale in euro moltiplicando l'eccesso per il costo medio per incidente equivalente (9.000 €):
   ```
   costo_sociale_eccesso_i = excess_EPDO_i × 9000
   ```

**Output**: colonne aggiuntive in `eb_results`: `EPDO_i`, `excess_EPDO_i`, `costo_sociale_eccesso`.

---

## FASE 4 — Indice composito di priorità

### Obiettivo
Costruire un indicatore multi-dimensionale che integri eccesso statistico, severità, vulnerabilità e rischio da velocità.

### Task 4.1 — Calcolo delle componenti

Per ogni sito, calcolare:

1. **Componente A — Eccesso EB pesato** (già calcolato):
   `A_i = excess_EPDO_i`

2. **Componente B — Indice di severità**:
   ```
   B_i = (n_mortali + n_feriti_gravi) / n_incidenti_totali
   ```
   (se n_incidenti_totali = 0, B_i = 0)

3. **Componente C — Indice di vulnerabilità utenti**:
   ```
   C_i = (n_incidenti_con_pedone + n_incidenti_con_ciclista) / n_incidenti_totali
   ```

4. **Componente D — Indicatore di rischio velocità**:
   ```
   D_i = 0.5 × (V85 / limite - 1)_+ + 0.5 × IQR_norm
   ```
   dove `(x)_+` = max(x, 0) — cioè conta solo l'eccesso di V85 sopra il limite.
   Per le intersezioni: media pesata del D degli archi afferenti.

### Task 4.2 — Normalizzazione e aggregazione

**Operazioni**:
1. Per ciascuna componente, normalizzare su scala 0-100:
   ```
   A_norm_i = 100 × (A_i - A_min) / (A_max - A_min)
   ```
   (analogamente per B, C, D). Usare i percentili 1° e 99° invece di min/max per evitare che outlier estremi comprimano la scala.

2. Calcolare l'indice composito con pesi configurabili:
   ```
   ICP_i = pA × A_norm + pB × B_norm + pC × C_norm + pD × D_norm
   ```
   Pesi default:
   ```python
   PESI_DEFAULT = {
       'eccesso_EB': 0.40,
       'severita': 0.25,
       'vulnerabilita': 0.20,
       'rischio_velocita': 0.15
   }
   ```

3. Classificare i siti in fasce:
   - ICP > 80° percentile → `priorità_altissima` (rosso scuro)
   - ICP 60°-80° percentile → `priorità_alta` (rosso)
   - ICP 40°-60° percentile → `priorità_media` (arancione)
   - ICP 20°-40° percentile → `priorità_bassa` (giallo)
   - ICP < 20° percentile → `monitoraggio` (verde)

### Task 4.3 — Matrice di rischio

**Operazioni**:
1. Per la vista decisionale, costruire anche la classificazione a matrice 2×2:
   - Asse X: `excess_EPDO_i` (alto/basso rispetto alla mediana)
   - Asse Y: `B_i` — indice di severità (alto/basso rispetto alla mediana)
   - Quadranti:
     - Q1 (alto/alto): **Intervento urgente**
     - Q2 (alto/basso): **Intervento programmato**
     - Q3 (basso/alto): **Indagine approfondita**
     - Q4 (basso/basso): **Monitoraggio**

**Output**: Tabella `priorita_finale` con tutti gli indicatori, l'ICP, la fascia di priorità, il quadrante della matrice.

### Task 4.4 — Analisi di sensibilità

**Operazioni**:
1. Variare i pesi dell'ICP (almeno 5 combinazioni diverse, es. "equi-pesato", "focus severità", "focus vulnerabilità", "focus EB", "focus velocità")
2. Per ciascuna combinazione, ricalcolare il ranking
3. Per ogni sito, calcolare:
   - Posizione media nel ranking across combinazioni
   - Posizione minima e massima
   - Flag `stabile` se sempre nei top N (es. N=50), `instabile` se entra/esce
4. Report di sensibilità: quanti dei top 50 sono stabili?

---

## FASE 5 — Dashboard e visualizzazione interattiva

### Obiettivo
Costruire un'interfaccia web per l'esplorazione e la comunicazione dei risultati.

### Scelta tecnologica
Per un prototipo rapido: **Dash (Plotly)** con mappa Mapbox/Leaflet — permette di avere tutto in Python.
Per la produzione: **React** + **Leaflet/Mapbox GL JS** + API backend Python (FastAPI).
Consiglio: partire con Dash per validare con i decisori, poi migrare a React per la versione pubblica.

### Task 5.1 — Mappa principale

**Specifiche**:
- Basemap: CartoDB Voyager (o simile, neutro)
- Layer intersezioni: cerchi colorati per fascia di priorità, dimensionati per volume di traffico
- Layer segmenti: linee colorate per fascia di priorità, spessore proporzionale al volume di traffico
- Scala cromatica: verde → giallo → arancione → rosso → rosso scuro (continua, non discreta)
- Zoom-dependent rendering:
  - Zoom < 12: heatmap aggregata (densità di ICP pesata)
  - Zoom 12-14: solo siti con priorità alta e altissima
  - Zoom > 14: tutti i siti
- Click su un sito → apre il pannello di dettaglio (Task 5.2)

### Task 5.2 — Pannello di dettaglio del sito

**Specifiche**:
Al click su un sito, mostrare:

1. **Header**: nome/localizzazione, posizione nel ranking (es. "#12 su 4.850 siti analizzati"), fascia di priorità con colore

2. **Radar chart / spider chart** delle 4 componenti normalizzate:
   - Eccesso EB
   - Severità
   - Vulnerabilità
   - Rischio velocità
   Con la media della rete sovrapposta come riferimento

3. **Dati incidentali**:
   - Totale incidenti nel periodo, disaggregati per gravità (barre orizzontali)
   - Incidenti osservati vs. attesi dalla SPF (grafico a barre: O_i vs E_i con evidenziazione dell'eccesso)
   - Andamento temporale anno per anno (linea)

4. **Dati di velocità**:
   - V85 vs limite (gauge chart)
   - Distribuzione delle velocità (V15, V25, V50, V75, V85 come box plot sintetico)

5. **Costo sociale**: stima del costo sociale dell'incidentalità in eccesso in €/anno

### Task 5.3 — Pannello filtri e viste

**Specifiche**:
- Filtro per municipio (dropdown o click sulla mappa)
- Filtro per categoria funzionale
- Filtro per fascia di priorità
- Filtro per tipologia di problema dominante (componente con valore più alto tra A, B, C, D)
- Toggle: mostra/nascondi intersezioni, mostra/nascondi segmenti
- Slider temporale: se avete dati su più periodi, possibilità di confrontare prima/dopo

### Task 5.4 — Vista decisionale

**Specifiche**:
- **Matrice di rischio**: scatter plot interattivo (eccesso EB vs severità), punti cliccabili
- **Cruscotto municipale**: tabella con i 15 municipi, per ciascuno:
  - Numero siti in fascia rossa/arancione
  - Top 5 siti con costo sociale più alto
  - Costo sociale totale stimato dell'incidentalità in eccesso
- **Classifica generale**: tabella paginata e ordinabile dei siti, con possibilità di esportare in CSV/Excel

### Task 5.5 — Export e reporting

**Specifiche**:
- Scheda singolo sito → PDF (1 pagina, formato A4 orizzontale, con mappa + radar chart + dati chiave)
- Top N siti → Excel con tutte le colonne
- Mappa → PNG ad alta risoluzione per presentazioni
- Report di sintesi → template Word/PDF con: metodologia (1 pagina), risultati aggregati (1 pagina), mappa cittadina (1 pagina), top 15 siti con schede (15 pagine)

---

## FASE 6 — Predisposizione al ri-calcolo

### Obiettivo
Garantire che il sistema sia facilmente aggiornabile con nuovi dati.

### Task 6.1 — Pipeline riproducibile

**Operazioni**:
1. Strutturare tutto il codice come una pipeline a step:
   ```
   01_pulizia_incidenti.py
   02_preparazione_rete.py
   03_matching_incidenti_rete.py
   04_calibrazione_spf.py
   05_calcolo_eb.py
   06_indice_composito.py
   07_export_dashboard.py
   ```
2. Ogni script legge i dati dal passaggio precedente e scrive l'output in un formato standard (GeoPackage o Parquet con geometria)
3. I parametri configurabili sono in un file di configurazione unico (`config.yaml`):
   ```yaml
   periodo_analisi:
     anno_inizio: 2017
     anno_fine: 2021
   matching:
     raggio_intersezione: 20
     soglia_snap_geometrica: 50
     soglia_snap_toponomastica: 100
   spf:
     modello_segmenti: "NB2"
     covariate_segmenti: ["log_TGM", "log_L"]
   indice_composito:
     peso_eccesso_eb: 0.40
     peso_severita: 0.25
     peso_vulnerabilita: 0.20
     peso_rischio_velocita: 0.15
   classificazione:
     soglie_percentili: [20, 40, 60, 80]
   ```
4. Un Makefile o script orchestratore (`run_pipeline.sh`) che esegue tutti gli step in sequenza

### Task 6.2 — Documentazione

1. README con: descrizione del progetto, prerequisiti, istruzioni di installazione, istruzioni di esecuzione
2. Docstring in ogni funzione
3. Un notebook Jupyter (`analisi_esplorativa.ipynb`) che documenta i risultati intermedi e le scelte fatte durante la calibrazione

---

## Dipendenze tra le fasi

```
FASE 0 (dati puliti)
  ├── Task 0.1 (incidenti) ──┐
  ├── Task 0.2 (TomTom)  ────┤
  └── Task 0.3 (PGTU+semaf.) ┘
           │
           ▼
FASE 1 (matching) ← dipende da tutti i Task 0.x
  ├── Task 1.1 (intersezioni) ──┐
  ├── Task 1.2 (segmenti)   ────┤
  └── Task 1.3 (assegnazione) ──┘
           │
           ▼
FASE 2 (SPF) ← dipende da Task 1.3
  ├── Task 2.1 (dataset regressione)
  ├── Task 2.2 (calibrazione)
  └── Task 2.3 (campioni piccoli)
           │
           ▼
FASE 3 (EB) ← dipende da Task 2.2
  ├── Task 3.1 (calcolo EB)
  └── Task 3.2 (pesatura EPDO)
           │
           ▼
FASE 4 (indice composito) ← dipende da Task 3.2
  ├── Task 4.1 (componenti)
  ├── Task 4.2 (aggregazione)
  ├── Task 4.3 (matrice)
  └── Task 4.4 (sensibilità)
           │
           ▼
FASE 5 (dashboard) ← dipende da Task 4.2
  └── tutti i task di visualizzazione
```

---

## Note per Claude Code

### Principi generali
- **Modularità**: ogni funzione fa una cosa sola ed è testabile indipendentemente
- **Tracciabilità**: ogni sito nel risultato finale deve essere riconducibile ai dati grezzi originali attraverso gli ID
- **Configurabilità**: tutti i parametri numerici (soglie, pesi, raggi) sono in `config.yaml`, mai hardcoded
- **Riproducibilità**: fissare i random seed dove necessario, versionare i dati intermedi

### Librerie Python richieste
```
geopandas >= 0.14
shapely >= 2.0
pandas >= 2.0
numpy
scipy
statsmodels
scikit-learn (per eventuali utilità)
matplotlib
plotly / dash (per il prototipo dashboard)
pyyaml
openpyxl (per export Excel)
fuzzywuzzy o rapidfuzz (per matching toponomastico)
reportlab o weasyprint (per export PDF)
```

### Struttura directory del progetto
```
roma_blackpoint/
├── config.yaml
├── run_pipeline.sh
├── README.md
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── s00_pulizia_incidenti.py
│   ├── s01_preparazione_rete.py
│   ├── s02_matching.py
│   ├── s03_spf.py
│   ├── s04_empirical_bayes.py
│   ├── s05_indice_composito.py
│   ├── s06_export.py
│   └── utils/
│       ├── geo_utils.py
│       ├── stats_utils.py
│       └── viz_utils.py
├── data/
│   ├── raw/          # dati originali (non versionati)
│   ├── interim/      # dati intermedi
│   └── processed/    # output finali
├── dashboard/
│   ├── app.py        # Dash app
│   ├── layouts.py
│   ├── callbacks.py
│   └── assets/
├── notebooks/
│   └── analisi_esplorativa.ipynb
├── reports/
│   └── templates/
└── tests/
    ├── test_matching.py
    ├── test_spf.py
    └── test_eb.py
```
