# Relazione di sviluppo e review del sistema
## "Who Gets Safe Streets?" — PSS equity-aware per la sicurezza stradale di Roma

> Parte I: cosa è stato realizzato, come funziona, quali risultati produce.
> Parte II: review critica dell'intero sistema con la lista prioritizzata
> di correzioni e miglioramenti.
>
> Stato al momento della stesura: pipeline `s00→s10` completa, dashboard a
> 8 tab, 223 test verdi, milestone M1–M4 tutte raggiunte.

---

# PARTE I — Cosa è stato realizzato

## 1. Il quadro

Il progetto è partito da un sistema "black point" esistente (identificazione
dei siti ad alta incidentalità con Empirical Bayes) ed è stato esteso a un
**Planning Support System completo** che chiude il ciclo delle politiche:

```
  MONITORAGGIO           DIAGNOSI                    PRESCRIZIONE
  (database s00-s02) →   rischio (s03-s07)      →    ottimizzazione (s09) → ┐
        ↑                + equità (s0c,s0d,s08)                             │
        └───────────── VALUTAZIONE (s10) ← interventi realizzati ←──────────┘
```

Ogni modulo è uno step riproducibile della pipeline (`run_pipeline.sh`),
parametrizzato in `config.yaml`, testato con fixture sintetiche a valori
noti, e servito da una tab interattiva della dashboard Dash.

## 2. I moduli, in dettaglio

### 2.1 Base dati (esistente, consolidata)
- `s00` pulizia incidenti (473.466 record 2004–2025, deduplicati, gravità a
  3 livelli, flag qualità geocodifica);
- `s01` rete TomTom (~94k archi) + classifica funzionale PGTU + semafori;
- `s02` matching: intersezioni (6.693 dopo il filtro dei falsi incroci),
  segmenti omogenei (61.931), assegnazione incidenti (92% abbinati);
- `s03` SPF binomiali negative per categoria; `s04` Empirical Bayes + EPDO
  (pesi 12/3/1); `s05` indice composito a 4 componenti; `s06` export.

### 2.2 Modulo A — High Injury Network + NKDE (`s07`)
**Cosa fa**: passa dalla diagnosi reattiva (dove sono accaduti gli
incidenti) a quella sistemica (dove si concentra e dove è atteso il danno).
- ranking dei segmenti per **KSI/km** (morti+feriti per km) stabilizzato
  con la stima EB;
- flag **HIN** per copertura cumulata (soglia 70% configurabile);
- curva di concentrazione rete→danno (`reports/hin_curva_concentrazione.csv`);
- **NKDE**: densità di incidenti *lungo la rete* per lixel da 20 m (kernel
  quartico 1D sull'ascissa curvilinea, bandwidth 200 m, pesi EPDO), con
  riaggancio degli incidenti d'intersezione al segmento più vicino.

**Risultato su Roma (2018–2021):**
> **Il 9,5% della rete (500 km su 5.243) concentra il 70% dei morti e
> feriti** — 4.774 segmenti HIN. NKDE: 128.733 lixel positivi, ~75 s.

### 2.3 Dati equità (`s0c`, `s0d`)
- **Censimento ISTAT 2021** per sezione: 23.591 sezioni (14.757 abitate,
  pop. 2.749.031), con derivazione di 5 indicatori di vulnerabilità
  (% bambini, % anziani, % stranieri, % istruzione bassa, % non occupati).
  Validazione forte: tutte le sezioni abitate hanno indicatori, POP21≡P1.
- **Database interventi**: 2.677 interventi in 13 tipologie (velox, isole
  ambientali, strade scolastiche, aree pedonali, ciclabili, GRAB, ponti,
  ZTL, puntuali/lineari/areali, ambiti), unificati da 16 sorgenti
  eterogenee con registro in config (nuove tipologie senza toccare codice).
  Data segnaposto 01/01/2025 + **override via CSV** per le date reali
  (anche future), con template auto-generato.

### 2.4 Modulo B — Equità distributiva (`s08` + `equity_utils`)
**La domanda di ricerca**: gli interventi vanno dove c'è bisogno
(rischio + vulnerabilità sociale) o altrove?
- vulnerabilità sociale 0–100 (composite index, 3 schemi di pesi per la
  sensibilità);
- rischio per sezione: excess EPDO ripartito per lunghezza intersecata;
- bisogno = media geometrica vulnerabilità×rischio;
- dotazione per tipologia (buffer sul raggio d'influenza / impronta);
- **Gini** e **concentration index** (rango frazionale pesato,
  Lerman–Yitzhaki), **LISA bivariata** (Moran locale BV, pesi KNN, seed
  fisso), choropleth 3×3 zero-inflated, **equity priority zones**.

**Risultati su Roma:**
> - **Concentration index = −0,098**: gli interventi si concentrano
>   moderatamente dove il bisogno è più basso (iniquità verticale).
> - **Robusto**: CI negativo con tutti e 3 gli schemi di pesi
>   (−0,096 / −0,107 / −0,096).
> - **Gini = 0,82**: dotazione fortemente concentrata nello spazio.
> - **2.582 equity priority zones** con **616.362 residenti**.
> - Per tipo: aree pedonali le più sbilanciate (CI −0,41, coerente con la
>   concentrazione nel centro storico); isole ambientali quasi neutre
>   (−0,03); velox −0,10.

### 2.5 Modulo C — Ottimizzazione (`s09` + `optim_utils`)
**Cosa fa**: dato un budget di p interventi e un raggio di copertura,
propone le localizzazioni ottime bilanciando rischio ed equità (MCLP,
Church & ReVelle 1974).
- domanda = 14.680 sezioni con `d_i(w) = (1−w)·rischio + w·vulnerabilità`;
- candidati = 2.561 siti (top per eccesso EPDO **+** siti nelle equity
  priority zones — senza questi le aree vulnerabili senza storico
  sarebbero irraggiungibili);
- solver greedy (garanzia 1−1/e) + esatto CBC opzionale, testati su
  istanza a ottimo noto;
- **frontiera di Pareto pre-calcolata** (11 punti in 2,5 s): la dashboard
  non risolve mai nulla nei callback.

**Risultato su Roma (budget 20, raggio 500 m):**
> | w | rischio coperto | vulnerabilità coperta |
> |---|---|---|
> | 0 (efficienza) | **34,3%** | 9,0% |
> | 0.5 | 32,4% | 11,6% |
> | 1 (equità) | 27,3% | **11,9%** |
>
> Cedere ~7 punti di rischio "compra" ~3 punti di vulnerabilità: il
> compromesso diventa esplicito e negoziabile (slider).
>
> Nota metodologica emersa: la prima frontiera era piatta perché (a) il
> "bisogno" composito contiene già il rischio e (b) i candidati
> solo-alto-rischio rendevano le aree vulnerabili irraggiungibili.
> Entrambe le scelte di disegno sono documentate — è un risultato utile
> per il paper.

### 2.6 Modulo D — Valutazione before-after (`s10`)
**Cosa fa**: per ogni intervento stima l'effetto causale θ (Crash
Modification Factor) col metodo EB di Hauer, correggendo la
regression-to-the-mean con le SPF di `s03`:
- associazione intervento→siti trattati (43.962 coppie);
- finestre pre/post (3+2 anni) troncate sulla disponibilità dati, con
  soglie minime di valutabilità (24 mesi pre, 12 post);
- θ con IC 95% aggregato sui siti; caso "zero incidenti dopo" con limite
  superiore Poisson;
- formule verificate su un caso calcolato a mano.

**Risultato con le date segnaposto (comportamento atteso e corretto):**
> 0 valutabili su 2.677 — 1.735 `post_insufficiente` (il "dopo" il
> 01/01/2025 ha ~una settimana di dati) + 942 `nessun_sito_trattato`.
> **La valutabilità è decisa dai dati, non dal codice**: alla prima data
> reale nel CSV di override, l'intervento esce con θ e IC senza alcuna
> modifica.

### 2.7 Dashboard (8 tab)
Mappa (con metriche KSI/km e NKDE + filtro "Solo HIN") · Analisi SPF ·
Analisi EB · Sensitività pesi · **Equità** (choropleth bivariata 3×3,
6 viste, Gini/CI ricalcolati al volo sui filtri, Lorenz, tabella
sensibilità) · **Scenari** (slider efficienza↔equità su scenari
pre-calcolati, frontiera di Pareto, siti proposti) · **Valutazione**
(stato interventi, forest plot θ+IC con empty-state esplicativo) ·
Vista decisionale.

### 2.8 Qualità e manutenzione
- **223 test** tutti verdi (inclusi i ~20 preesistenti riallineati:
  pesi EPDO, schema `n_feriti`, componente D, matrice al 75° percentile,
  filtro falsi incroci);
- **warning GitHub >50 MB eliminati**: export GeoJSON 2D a 6 decimali,
  versionata la sola copia compressa (5 MB vs 51);
- fix reali trovati facendo girare i dati: `pyarrow` mancante dai
  requirements, adattatore schema `match_type/id_match`, filtro anni SPF
  nella NKDE, geometrie censuarie invalide riparate, bordo half-open
  delle finestre temporali.

---

# PARTE II — Review del sistema

Review critica dell'intero sistema, con priorità. Legenda:
🔴 correggere prima di usare i numeri · 🟠 sistemare prima della
submission del paper · 🟡 miglioramento opportuno · ⚪ nice-to-have.

## A. Bug e difetti di correttezza

1. 🔴 **`s07` non è idempotente** *(confermato con test)*: riscrive
   `priorita_finale.gpkg` aggiungendo colonne; un secondo run senza
   rifare `s05` fa collidere il merge di `nkde_max` (suffissi `_x/_y` →
   `KeyError`). Fix: drop preventivo delle colonne `ksi_km/is_hin/
   rank_ksi/nkde_max` all'inizio di `main`, o scrittura su file separato.
2. 🟡 **Centroidi dashboard calcolati in CRS geografico** (`app.py`):
   warning a ogni avvio e lieve imprecisione. Fix: centroide nel CRS
   metrico, poi riproiezione.
3. 🟡 **`s08`: intersezioni con predicato `within`** — un punto
   esattamente sul confine di sezione viene perso. Effetto trascurabile
   ma facile da chiudere (`intersects` + dedup).
4. 🟡 **`s10`: il periodo lavori non è escluso** — `data_fine` esiste
   nello schema interventi ma le finestre usano solo `data_attivazione`;
   quando le date reali includeranno cantieri lunghi, il "durante" va
   escluso dal prima e dal dopo.

## B. Questioni metodologiche (prima della submission)

5. 🔴 **La dotazione mescola realizzato, pianificato e scenario**: la
   rete ciclabile (1.864 elementi, 70% del totale) include tratte di
   scenario PUMS; il CI attuale fotografa il *database progetti*, non il
   costruito. Fix: filtro per `fase` in `s08` (`tipi_dotazione` +
   `fasi_dotazione` in config) appena le fasi si consolidano; nel
   frattempo, nel paper usare i **CI per tipologia** e dichiarare la
   natura del dato.
6. 🔴 **`dot_totale` è dominato dalle ciclabili**: il CI complessivo
   (−0,098) è trainato da un solo tipo. Alternativa: media dei CI per
   tipo, o dotazione pesata per "capacità protettiva" del tipo.
7. 🟠 **MAUP: la seconda scala spaziale promessa non è implementata** —
   il piano (T0.3) prevede sezioni + griglia ~500 m; oggi esiste solo la
   scala sezione. Serve `spatial_units.py` + run di sensibilità (i
   revisori la chiederanno).
8. 🟠 **Contaminazione del baseline nel before-after**: le SPF sono
   calibrate sul 2018–2021; un intervento realizzato in quegli anni ha
   già parte del suo effetto dentro `E_i` → θ sottostimato. Mitigazioni:
   ricalibrare le SPF sui soli siti non trattati, o dichiarare il bias.
9. 🟠 **Manca il gruppo di controllo e l'ITS** in `s10` (estensioni
   dichiarate): da implementare col primo caso reale datato — il paper
   ha bisogno di almeno un caso con EB + ITS concordi.
10. 🟠 **NKDE entro-segmento**: il kernel non attraversa le
    intersezioni (dichiarato). Con bandwidth 200 m su segmenti mediani
    ~85 m l'effetto non è piccolo; valutare l'estensione 1-hop o
    dichiarare con un test di sensibilità sulla bandwidth.
11. 🟠 **MCLP semplificato**: copertura binaria (dentro/fuori),
    raggio euclideo (non di rete), tipi di intervento indistinti,
    nessuna riduzione attesa del rischio (si massimizza il raggiunto,
    non l'evitato). Tutti dichiarati; il più impattante da migliorare è
    il **decadimento della copertura** con la distanza.
12. 🟡 **`perc_non_occupati` è una proxy grezza** (include studenti e
    pensionati anticipati nei 15–64); senza reddito a scala di sezione
    resta la scelta obbligata — dichiararla e testarla nella sensibilità
    (già fatto in parte con `focus_deprivazione`).
13. 🟡 **Underreporting di pedoni/ciclisti** nei dati incidenti:
    distorce KSI, NKDE ed equità nelle zone ad alta mobilità attiva.
    Da dichiarare come limite (letteratura abbondante).
14. 🟡 **La "vulnerabilità utenti" (componente C) e l'equità (s08)
    restano concettualmente distinte** — bene così, ma il paper deve
    spiegarlo esplicitamente per evitare confusione dei revisori.

## C. Robustezza del dato e del flusso

15. 🔴 **`id_intervento` dipende dall'ordine delle righe della
    sorgente**: se un GeoPackage viene rigenerato con ordine diverso,
    gli override di date puntano a interventi sbagliati **in silenzio**.
    Fix: usare l'id di sorgente dove esiste (es. `NOME` dei velox,
    `cod prog` delle strade scolastiche) e un controllo di coerenza
    (hash della geometria) che avvisi se l'abbinamento id→geometria
    cambia.
16. 🟠 **942 interventi "nessun_sito_trattato"**: in gran parte tratte
    ciclabili di scenario lontane dalla rete TomTom analizzata, ma il
    numero è alto — merita un report diagnostico per tipo (quali
    tipologie restano fuori e perché).
17. 🟡 **Le date segnaposto sono indistinguibili a valle senza
    guardare `data_stato`**: i moduli lo gestiscono, ma un log di
    warning aggregato ("X interventi con data segnaposto") in `s08`/`s10`
    renderebbe impossibile dimenticarselo.
18. 🟡 **Qualità geocodifica post-05/2022**: il piano la segnala come
    da ri-verificare; il filtro `flag_qualita: alta` protegge, ma la
    quota di incidenti 2022–2025 esclusa andrebbe quantificata nel
    report di matching.

## D. Ingegneria e qualità del software

19. 🟠 **Nessun test sui callback della dashboard** (solo smoke di
    import e HTTP 200): i 4 moduli di tab meritano test con
    `dash.testing` o almeno test unitari delle funzioni-figura.
20. 🟠 **Niente CI**: aggiungere GitHub Actions con `pytest -q` (i test
    girano senza dati reali, quindi è gratis).
21. 🟡 **Avvio dashboard lento (~15–20 s)**: carica tre GeoPackage e
    semplifica le geometrie a ogni avvio. Fix: cache Parquet/GeoParquet
    degli oggetti pre-processati, invalidata sull'mtime dei sorgenti.
22. 🟡 **History git pesante**: i blob >50 MB storici restano nella
    cronologia; prima della release open-source serve la riscrittura
    (`git filter-repo`) già documentata nel README.
23. 🟡 **Duplicazioni minori nel codice dashboard**:
    `STILE_TITOLO_CARD_LOCAL` duplica `STILE_TITOLO_CARD` di layouts;
    palette e stili andrebbero centralizzati in un modulo `theme`.
24. ⚪ **`s0d`: il QGIS project (.qgz) è versionato ma non usato** dal
    codice — ok come documentazione delle sorgenti, da dichiarare nel
    README.
25. ⚪ **Naming misto italiano/inglese** (`theta`, `frontiera`,
    `excess_EPDO_i`): coerente col repo, ma per la release open-source
    conviene un glossario nel README.

## E. Per il paper (WP5, prossimo)

26. 🟠 **Figure riproducibili**: manca `reports/paper/` con export a
    300 dpi di: curva di concentrazione HIN, choropleth bivariata,
    Lorenz, frontiera di Pareto, (forest plot quando ci saranno date).
27. 🟠 **Tabella MAUP** (dipende dal punto 7) e tabella di sensibilità
    completa (pesi × scala × tipi di dotazione).
28. 🟡 **Release citabile**: tag + archivio Zenodo/DOI alla submission.

## Sintesi delle priorità

**Da fare subito (prima di usare i numeri in pubblico):**
il fix di idempotenza di `s07` (#1), gli id stabili degli interventi
(#15) e la consapevolezza che il CI attuale misura il *database
progetti* (#5–6).

**Da fare prima della submission:** seconda scala MAUP (#7), gruppo di
controllo/ITS sul primo caso datato (#8–9), figure riproducibili (#26),
CI su GitHub (#20).

**Il sistema è solido nel suo nucleo**: le formule statistiche sono
testate su casi a mano, i limiti sono dichiarati dove sono, e il flusso
dati→risultato è riproducibile end-to-end con un solo comando.
