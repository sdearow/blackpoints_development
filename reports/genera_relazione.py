"""Genera la relazione metodologica in formato Word (.docx)."""

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from pathlib import Path


def _stile_doc(doc: Document) -> None:
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(11)
    font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
    pf = style.paragraph_format
    pf.space_after = Pt(6)
    pf.line_spacing = 1.15

    for lvl, (nome, sz, bold) in enumerate([
        ("Heading 1", 16, True),
        ("Heading 2", 13, True),
        ("Heading 3", 11.5, True),
    ]):
        s = doc.styles[nome]
        s.font.name = "Calibri"
        s.font.size = Pt(sz)
        s.font.bold = bold
        s.font.color.rgb = RGBColor(0x0D, 0x2B, 0x52)
        s.paragraph_format.space_before = Pt(14)
        s.paragraph_format.space_after = Pt(4)


def _p(doc, testo, style="Normal", bold=False, italic=False):
    p = doc.add_paragraph(testo, style=style)
    if bold or italic:
        for run in p.runs:
            run.bold = bold
            run.italic = italic
    return p


def genera():
    doc = Document()
    _stile_doc(doc)

    # ========== TITOLO ==========
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("Relazione Metodologica\n")
    r.font.size = Pt(22)
    r.font.bold = True
    r.font.color.rgb = RGBColor(0x0D, 0x2B, 0x52)
    r2 = t.add_run("Sistema di Identificazione dei Black Point Incidentali\n"
                    "Rete Stradale del Comune di Roma Capitale")
    r2.font.size = Pt(14)
    r2.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
    doc.add_paragraph()

    # ========== 1. PREMESSA ==========
    doc.add_heading("1. Premessa e obiettivi del lavoro", level=1)

    _p(doc, (
        "Il presente documento descrive la metodologia adottata per la costruzione "
        "di un sistema prototipale di identificazione e classificazione dei black point "
        "incidentali sulla rete stradale del Comune di Roma Capitale. "
        "Il sistema si propone di individuare i siti (segmenti stradali e intersezioni) "
        "che presentano una concentrazione anomala di incidenti rispetto a quanto atteso "
        "sulla base delle caratteristiche geometriche e di traffico della rete, "
        "e di ordinarli secondo un indice composito di priorità che tenga conto non solo "
        "della frequenza ma anche della gravità, della vulnerabilità degli utenti deboli "
        "e del rischio legato alla dispersione delle velocità operative."
    ))

    _p(doc, (
        "L'approccio metodologico si fonda sui principi consolidati della Network Safety Analysis "
        "descritti nell'Highway Safety Manual (AASHTO, 2010) e nella letteratura internazionale "
        "sulla sicurezza stradale, con particolare riferimento ai lavori di Hauer (1997) "
        "sull'Empirical Bayes e alla normativa europea sulla gestione della sicurezza delle "
        "infrastrutture stradali (Direttiva 2008/96/CE, aggiornata dalla Direttiva 2019/1936). "
        "Il metodo adottato è coerente con le linee guida del Highway Safety Manual (HSM) e "
        "con la prassi consolidata nella letteratura di settore (Persaud et al., 1999; "
        "Montella, 2010; La Torre et al., 2019)."
    ))

    _p(doc, (
        "Il sistema è stato sviluppato integrando diverse fonti dati: il database incidentale "
        "del Comune di Roma (periodo 2010–2024), il grafo stradale TomTom con dati di traffico "
        "e velocità istantanee, il grafo PGTU 2026 del Comune con la classificazione funzionale "
        "delle strade, e il catasto degli impianti semaforici. L'intera pipeline di elaborazione "
        "è implementata in Python ed è completamente riproducibile a partire dai dati grezzi."
    ))

    _p(doc, (
        "L'obiettivo finale è fornire all'Amministrazione uno strumento operativo per la "
        "programmazione degli interventi di messa in sicurezza della rete, basato su criteri "
        "oggettivi, trasparenti e scientificamente fondati. La dashboard interattiva che "
        "accompagna il modello consente l'esplorazione dei risultati, l'analisi di sensitività "
        "dei pesi e la consultazione della classifica dei siti prioritari."
    ))

    # ========== 2. DESCRIZIONE DELLA METODOLOGIA ==========
    doc.add_heading("2. Descrizione della metodologia", level=1)

    _p(doc, (
        "La metodologia si articola in sei fasi sequenziali, ciascuna delle quali produce "
        "output intermedi utilizzati dalle fasi successive. Il flusso complessivo è il seguente:"
    ))

    _p(doc, (
        "Fase 0 – Acquisizione e pulizia dei dati (incidenti, rete stradale, semafori)\n"
        "Fase 1 – Matching spaziale degli incidenti sulla rete\n"
        "Fase 2 – Calibrazione delle Safety Performance Functions (SPF)\n"
        "Fase 3 – Stima Empirical Bayes e calcolo EPDO\n"
        "Fase 4 – Costruzione dell'indice composito di priorità (ICP)\n"
        "Fase 5 – Export dei risultati e dashboard interattiva"
    ))

    _p(doc, (
        "Il sistema di riferimento metrico utilizzato per tutti i calcoli geometrici "
        "è UTM zona 33N (EPSG:32633); la visualizzazione finale avviene in WGS84 (EPSG:4326)."
    ))

    # ========== 2.1 FASE 0 ==========
    doc.add_heading("2.1. Fase 0 – Acquisizione e pulizia dei dati", level=2)

    doc.add_heading("2.1.1. Database incidentale", level=3)
    _p(doc, (
        "Il database incidentale del Comune di Roma è costituito da più file CSV che coprono "
        "il periodo 2004–2024, derivanti da diverse campagne di rilevazione e rigeolocalizzazione. "
        "I file includono il dataset storico (Incidenti_1, 2004–2022), un estratto intermedio "
        "(Incidenti_2, 2024–2025) e le rigeolocalizzazioni annuali (Incidenti_2022, 2023, 2024) "
        "che hanno priorità in caso di duplicati."
    ))

    _p(doc, (
        "La procedura di pulizia esegue le seguenti operazioni:\n"
        "• Deduplica su identificativo univoco (idprotocollo): quando lo stesso incidente "
        "compare in più file, viene conservata la versione proveniente dal file con priorità "
        "più alta (le rigeolocalizzazioni annuali hanno priorità massima).\n"
        "• Standardizzazione dei campi: le coordinate originali in Gauss-Boaga zona 2 (EPSG:3004) "
        "vengono riproiettate nel sistema metrico di lavoro (EPSG:32633).\n"
        "• Normalizzazione toponomastica: espansione delle abbreviazioni tipiche della viabilità "
        "romana (V. → Via, P.zza → Piazza, V.le → Viale, ecc.) e uniformazione delle maiuscole.\n"
        "• Classificazione della gravità in tre livelli: mortale (n_morti > 0), ferito "
        "(n_feriti > 0 con n_morti = 0), solo danni (altrimenti). Il dataset originale non "
        "distingue tra feriti gravi e lievi; pertanto si adotta un'unica categoria «feriti».\n"
        "• Calcolo del flag di qualità della geocodifica (alta, media, bassa) basato sulla "
        "presenza di coordinate valide, sul campo di conferma (ok) e sulla specificità della "
        "localizzazione (intersezione, in corrispondenza di, in prossimità).\n"
        "• Filtro spaziale: vengono mantenuti solo gli incidenti che ricadono entro il confine "
        "comunale, approssimato dal convex hull della rete TomTom con buffer di 200 m.\n"
        "• Filtro di qualità: per la calibrazione dei modelli vengono utilizzati solo gli "
        "incidenti con flag di qualità «alta», al fine di garantire l'affidabilità della "
        "localizzazione spaziale."
    ))

    doc.add_heading("2.1.2. Rete stradale TomTom", level=3)
    _p(doc, (
        "La rete stradale di riferimento è il grafo TomTom 2024, composto da circa 94.000 archi "
        "con geometria MultiLineString Z e attributi di traffico e velocità osservata. Per ogni arco "
        "sono disponibili:\n"
        "• TGM (Traffic Giornaliero Medio): veicoli/giorno totali.\n"
        "• Velocità istantanea rilevata dai probe GPS: distribuzione completa sotto forma di "
        "percentili dal 5° al 95° (in particolare la V85, l'85° percentile, proxy della velocità operativa).\n"
        "• Limite di velocità vigente.\n"
        "• Classe funzionale FRC (Functional Road Class, scala TomTom 0–7).\n"
        "• Toponimo (StreetName), già normalizzato nella sorgente."
    ))

    _p(doc, (
        "La preparazione della rete include:\n"
        "• Validazione topologica: rimozione degli archi con geometria nulla, vuota o invalida.\n"
        "• Calcolo delle covariate derivate per i modelli SPF: log(TGM), log(lunghezza in km), "
        "IQR normalizzato delle velocità (dispersione), rapporto V85/limite.\n"
        "• Join spaziale con il grafo PGTU 2026 del Comune per ereditare la classificazione "
        "funzionale aggiornata (S, IQ, IZ, Q), il flag di grande viabilità e quello di trasporto "
        "pubblico locale. Il join avviene per punto mediano (midpoint) dell'arco TomTom verso "
        "l'arco PGTU più vicino entro 15 m.\n"
        "• Classificazione delle strade extraurbane del Comune e di quelle gestite da altri enti "
        "(autostrade, ANAS), per la corretta stratificazione dei modelli SPF."
    ))

    doc.add_heading("2.1.3. Impianti semaforici", level=3)
    _p(doc, (
        "Il catasto degli impianti semaforici del Comune di Roma contiene la posizione geografica "
        "e il tipo di ogni impianto (veicolare o pedonale). In fase di preparazione:\n"
        "• I toponimi vengono normalizzati con le stesse regole del database incidentale.\n"
        "• Viene applicata una correzione di offset sistematico (dx = 0.9 m, dy = 6.4 m) "
        "calcolata empiricamente come mediana dello scostamento dei semafori rispetto alla rete TomTom.\n"
        "• Solo i semafori veicolari vengono utilizzati per definire le intersezioni semaforizzate."
    ))

    # ========== 2.2 FASE 1 ==========
    doc.add_heading("2.2. Fase 1 – Matching spaziale incidenti-rete", level=2)

    doc.add_heading("2.2.1. Estrazione delle intersezioni", level=3)
    _p(doc, (
        "Le intersezioni vengono estratte automaticamente dal grafo TomTom identificando i nodi "
        "con grado topologico ≥ 3 (almeno tre archi convergenti). L'algoritmo opera come segue:\n"
        "• Estrazione degli endpoint (start/end) di ciascun arco.\n"
        "• Clustering degli endpoint entro una tolleranza di 1.5 m tramite KD-tree e "
        "union-find per gestire piccoli disallineamenti topologici.\n"
        "• Calcolo del grado di ciascun nodo (numero di archi distinti convergenti).\n"
        "• Selezione dei nodi con grado ≥ 3 come candidati-intersezione."
    ))

    _p(doc, (
        "Il grafo TomTom genera un numero molto elevato di falsi positivi: nodi a grado 3–4 che "
        "non corrispondono a veri incroci ma a confluenze di carreggiate separate, svincoli a livelli "
        "sfalsati o micro-segmentazioni della rete. Per filtrare questi artefatti si applicano tre "
        "criteri progressivi:\n"
        "• Filtro mono-toponimo: nodi a grado 3–4 con un solo toponimo distinto tra gli archi "
        "convergenti vengono rimossi (carreggiate separate della stessa strada).\n"
        "• Filtro FRC uniforme: nodi a grado 3–4 dove tutti gli archi hanno la stessa classe "
        "funzionale FRC e al massimo due toponimi vengono rimossi (biforcazioni senza cambio "
        "di classificazione).\n"
        "• Cluster di prossimità: nodi entro 30 m che condividono almeno un toponimo vengono "
        "fusi in un unico nodo (il rappresentante con grado più alto), eliminando le false "
        "intersezioni generate da micro-segmentazioni."
    ))

    _p(doc, (
        "Dopo il filtraggio, ogni intersezione viene arricchita con l'informazione di "
        "semaforizzazione tramite join spaziale con il catasto dei semafori veicolari: un'intersezione "
        "è classificata come semaforizzata se almeno un semaforo veicolare le è stato associato."
    ))

    doc.add_heading("2.2.2. Costruzione dei segmenti omogenei", level=3)
    _p(doc, (
        "I segmenti omogenei vengono costruiti concatenando archi TomTom consecutivi che condividono "
        "lo stesso toponimo e presentano una variazione del TGM contenuta (< 30%). La segmentazione "
        "si interrompe:\n"
        "• A ogni intersezione reale (nodo di grado ≥ 3 che ha superato i filtri).\n"
        "• Al cambio di toponimo.\n"
        "• Quando la variazione relativa del TGM tra archi consecutivi supera la soglia del 30%.\n"
        "• Quando la lunghezza cumulata supera 2.000 m (lunghezza massima di un segmento omogeneo)."
    ))

    _p(doc, (
        "Per ciascun segmento vengono calcolati gli attributi aggregati degli archi componenti: "
        "TGM medio, V85 media, limite di velocità medio, IQR normalizzato medio (tutti pesati per "
        "lunghezza dell'arco), classe FRC modale e classificazione PGTU modale. I segmenti con "
        "lunghezza inferiore a 100 m sono marcati come «corti» ma vengono comunque inclusi "
        "nell'analisi."
    ))

    doc.add_heading("2.2.3. Assegnazione degli incidenti alla rete", level=3)
    _p(doc, (
        "L'abbinamento di ciascun incidente al sito della rete avviene secondo una gerarchia "
        "di criteri con priorità decrescente:\n"
        "1. Intersezione: se l'incidente ricade entro un raggio di 25 m da un nodo-intersezione, "
        "viene assegnato a quell'intersezione. Questa priorità riflette il fatto che gli incidenti "
        "avvenuti in prossimità degli incroci hanno caratteristiche distinte (conflitti di "
        "traiettoria, svolta, attraversamento pedonale).\n"
        "2. Segmento geometrico: se l'incidente non ricade in un'intersezione, viene assegnato "
        "al segmento più vicino entro una soglia di 30 m.\n"
        "3. Fallback toponomastico: per gli incidenti residui si cerca un segmento entro 100 m "
        "il cui toponimo corrisponda al nome strada dell'incidente con un punteggio fuzzy "
        "(token_set_ratio, libreria rapidfuzz) ≥ 85. Tra i candidati compatibili viene scelto "
        "il più vicino geometricamente.\n"
        "4. Non abbinato: gli incidenti che non soddisfano nessuno dei criteri precedenti restano "
        "esclusi dall'analisi."
    ))

    _p(doc, (
        "La procedura include un'asserzione di integrità: il numero totale di assegnazioni deve "
        "coincidere con il numero di incidenti in ingresso (nessun doppio conteggio)."
    ))

    # ========== 2.3 FASE 2 ==========
    doc.add_heading("2.3. Fase 2 – Safety Performance Functions (SPF)", level=2)

    _p(doc, (
        "Le Safety Performance Functions sono modelli di regressione che stimano il numero atteso "
        "di incidenti per un sito «strutturalmente simile» sulla base delle sue caratteristiche "
        "di traffico e geometria. Il valore predetto dalla SPF rappresenta la performance "
        "«media» della rete per quella classe di siti, ed è il riferimento rispetto al quale "
        "l'Empirical Bayes calcola l'eccesso o il deficit di incidentalità."
    ))

    doc.add_heading("2.3.1. Struttura del modello", level=3)
    _p(doc, (
        "Il modello adottato è la regressione binomiale negativa di tipo NB2 (Cameron e Trivedi, "
        "1998), standard nella letteratura sulla sicurezza stradale per la sua capacità di gestire "
        "la sovradispersione tipica dei conteggi incidentali. La distribuzione binomiale negativa "
        "introduce un parametro aggiuntivo α (overdispersion) rispetto alla Poisson, il cui inverso "
        "k = 1/α è fondamentale per il calcolo del peso Empirical Bayes."
    ))

    _p(doc, (
        "Per i segmenti, il modello base assume la forma:\n"
        "    E(Y_i) = exp(β0 + β1 · log(TGM_i) + β2 · log(L_i) + log(n_anni))\n"
        "dove Y_i è il conteggio degli incidenti nel periodo di analisi, TGM_i è il traffico "
        "giornaliero medio, L_i è la lunghezza del segmento in km, e log(n_anni) è l'offset "
        "per normalizzare rispetto alla durata del periodo di osservazione."
    ))

    _p(doc, (
        "Per le intersezioni, il modello base è:\n"
        "    E(Y_i) = exp(β0 + β1 · log(flusso_entrante_i) + log(n_anni))\n"
        "dove flusso_entrante_i è la somma dei TGM degli archi convergenti divisa per 2 "
        "(per evitare il doppio conteggio dei flussi bidirezionali)."
    ))

    _p(doc, (
        "Vengono calibrati anche modelli estesi che includono covariate aggiuntive:\n"
        "• Per i segmenti: V85 (velocità operativa) e IQR normalizzato (dispersione delle velocità).\n"
        "• Per le intersezioni: numero di bracci.\n"
        "Il modello esteso viene adottato solo se produce un miglioramento dell'AIC (Akaike "
        "Information Criterion) rispetto al modello base."
    ))

    doc.add_heading("2.3.2. Stratificazione per categoria", level=3)
    _p(doc, (
        "I modelli SPF vengono calibrati separatamente per ciascuna categoria funzionale, "
        "in quanto le relazioni tra traffico e incidentalità differiscono significativamente "
        "tra tipologie di strada:\n"
        "• Segmenti: la categoria SPF è derivata dalla classificazione PGTU 2026 "
        "(IQ – Interquartiere, IZ – Interzonale, Q – Quartiere), con le strade «S» "
        "(Scorrimento) accorpate in IQ, le strade extraurbane del Comune in una categoria dedicata "
        "e le strade locali (non presenti nel grafo PGTU) nella categoria LOCALE. Le categorie "
        "con meno di 50 siti vengono accorpate in LOCALE.\n"
        "• Intersezioni: la stratificazione avviene per stato di semaforizzazione "
        "(semaforizzata / non semaforizzata)."
    ))

    # ========== 2.4 FASE 3 ==========
    doc.add_heading("2.4. Fase 3 – Stima Empirical Bayes (EB) e EPDO", level=2)

    doc.add_heading("2.4.1. Il metodo Empirical Bayes", level=3)
    _p(doc, (
        "L'Empirical Bayes (Hauer, 1997) è il metodo di riferimento per la stima della "
        "sicurezza di un sito stradale perché combina due fonti di informazione complementari:\n"
        "• La predizione del modello SPF (E_i), che rappresenta la performance media di siti "
        "strutturalmente simili: è stabile ma non tiene conto delle specificità locali.\n"
        "• Il conteggio osservato (O_i), che riflette le condizioni reali del sito: è specifico "
        "ma soggetto a fluttuazione casuale (un incidente mortale in più o in meno può essere "
        "dovuto al caso)."
    ))

    _p(doc, (
        "La stima EB combina le due fonti assegnando un peso (w_i) che dipende dalla "
        "precisione relativa del modello rispetto all'osservato:\n"
        "    w_i = 1 / (1 + E_i · k)\n"
        "    EB_i = w_i · E_i + (1 - w_i) · O_i\n"
        "dove k = 1/α è il parametro di sovradispersione del modello NB2."
    ))

    _p(doc, (
        "Quando E_i è grande (siti ad alto flusso con molti dati), il peso w_i tende a zero "
        "e la stima EB coincide con l'osservato: il modello «si fida» dei dati. Quando E_i è "
        "piccolo (siti a basso flusso, pochi incidenti attesi), w_i tende a 1 e la stima EB "
        "converge verso la predizione SPF: il modello «protegge» dall'effetto regression-to-the-mean."
    ))

    _p(doc, (
        "L'eccesso atteso è definito come:\n"
        "    excess_i = EB_i - E_i\n"
        "Un eccesso positivo indica che il sito ha più incidenti di quanti ne avrebbe un sito "
        "medio con le stesse caratteristiche: è quindi un potenziale black point."
    ))

    doc.add_heading("2.4.2. EPDO – Equivalent Property Damage Only", level=3)
    _p(doc, (
        "Il conteggio grezzo degli incidenti non distingue tra un tamponamento con soli danni "
        "materiali e un incidente mortale. L'EPDO (Equivalent Property Damage Only) è una metrica "
        "che pondera gli incidenti per gravità attribuendo un peso relativo a ciascuna categoria:\n"
        "• Incidente mortale: peso 12\n"
        "• Incidente con feriti: peso 3\n"
        "• Incidente con soli danni: peso 1\n"
        "I pesi adottati sono quelli classici di Hauer (1997) / AASHTO, scelti perché "
        "moderati e consolidati nella letteratura, evitando che un singolo evento mortale "
        "casuale domini la classifica."
    ))

    _p(doc, (
        "L'eccesso EB viene pesato con il rapporto EPDO medio del sito per ottenere "
        "l'excess_EPDO_i, che costituisce la componente A dell'indice composito."
    ))

    doc.add_heading("2.4.3. Costo sociale", level=3)
    _p(doc, (
        "Parallelamente all'EPDO (usato per la prioritizzazione), il sistema calcola anche "
        "il costo sociale dell'eccesso di incidentalità utilizzando i costi unitari MEF/ISTAT "
        "(valori 2022):\n"
        "• Decesso: 1.500.000 €\n"
        "• Ferito (blend 15% grave + 85% lieve): 48.300 €\n"
        "• Solo danni: 9.000 €\n"
        "Questo valore non entra nel calcolo dell'ICP ma viene riportato nei risultati per "
        "consentire valutazioni economiche degli interventi."
    ))

    # ========== 2.5 FASE 4 ==========
    doc.add_heading("2.5. Fase 4 – Indice Composito di Priorità (ICP)", level=2)

    _p(doc, (
        "L'indice composito di priorità (ICP) aggrega quattro componenti complementari, "
        "ciascuna delle quali cattura un aspetto diverso della pericolosità del sito. "
        "L'approccio multi-criterio consente di bilanciare la frequenza degli incidenti con "
        "la loro gravità, la vulnerabilità degli utenti deboli e le condizioni operative "
        "della strada."
    ))

    doc.add_heading("2.5.1. Le quattro componenti", level=3)
    _p(doc, (
        "Componente A – Eccesso EB pesato (peso default: 40%)\n"
        "È l'excess_EPDO_i, ovvero l'eccesso di incidentalità rispetto al modello SPF, "
        "pesato per la gravità media del sito. È la componente più importante: identifica i siti "
        "che hanno statisticamente più incidenti del previsto, al netto delle fluttuazioni "
        "casuali (grazie all'EB) e della composizione per gravità (grazie all'EPDO)."
    ))

    _p(doc, (
        "Componente B – Indice di severità (peso default: 25%)\n"
        "Rapporto tra il numero di incidenti con esito grave (mortali + feriti) e il totale "
        "degli incidenti, moltiplicato per un fattore di credibilità:\n"
        "    B_i = [(n_mortali + n_feriti) / n_incidenti] · min(n_incidenti, 5) / 5\n"
        "Il fattore di credibilità smorza i siti con pochissimi incidenti (1–4) dove il "
        "rapporto è statisticamente instabile: un sito con 1 solo incidente mortale avrebbe "
        "B = 1.0 (100% mortali), ma questa informazione è scarsamente affidabile. Il fattore "
        "raggiunge il valore massimo di 1 quando il sito ha almeno 5 incidenti."
    ))

    _p(doc, (
        "Componente C – Indice di vulnerabilità utenti (peso default: 20%)\n"
        "Rapporto tra il numero di incidenti che coinvolgono pedoni e il totale degli incidenti, "
        "anch'esso moltiplicato per il fattore di credibilità:\n"
        "    C_i = [n_pedoni / n_incidenti] · min(n_incidenti, 5) / 5\n"
        "Questa componente penalizza i siti dove la quota di utenti deboli coinvolti è "
        "particolarmente elevata, indirizzando gli interventi verso le situazioni di "
        "maggiore disparità tra infrastruttura e utenza."
    ))

    _p(doc, (
        "Componente D – Dispersione delle velocità (peso default: 15%)\n"
        "Per i segmenti: IQR normalizzato delle velocità istantanee (rapporto tra "
        "l'interquartile V75−V25 e il limite di velocità), indicatore di disomogeneità "
        "del comportamento di guida.\n"
        "Per le intersezioni: media pesata per TGM dell'IQR normalizzato degli archi convergenti.\n"
        "Una dispersione elevata segnala situazioni dove coesistono veicoli molto lenti e molto "
        "veloci, tipiche di tratti con geometria confusa, accessi laterali non regolati o "
        "transizioni tra ambienti stradali diversi."
    ))

    doc.add_heading("2.5.2. Normalizzazione delle componenti", level=3)
    _p(doc, (
        "Le quattro componenti hanno scale e distribuzioni molto diverse tra loro: l'eccesso EB "
        "può variare da −50 a +200, mentre i rapporti di severità sono compresi tra 0 e 1. "
        "Per renderle confrontabili, ciascuna componente viene normalizzata su scala 0–100 "
        "tramite percentili robusti (1° e 99° percentile), secondo la formula:\n"
        "    X_norm = 100 · (X - P1) / (P99 - P1),  clippato a [0, 100]"
    ))

    _p(doc, (
        "Per le componenti con distribuzione fortemente zero-inflated (tipicamente B e C sui "
        "segmenti, dove oltre il 50% dei siti non ha incidenti con feriti o pedoni), si applica "
        "una normalizzazione separata: i valori nulli restano a 0, mentre i valori positivi "
        "vengono normalizzati nell'intervallo [1, 100] sulla sotto-distribuzione dei soli "
        "valori > 0. Questo evita che la massa di zeri comprima la scala e renda "
        "indistinguibili i siti con valori positivi."
    ))

    doc.add_heading("2.5.3. Calcolo dell'ICP e classificazione", level=3)
    _p(doc, (
        "L'ICP è la media ponderata delle quattro componenti normalizzate:\n"
        "    ICP_i = wA · A_norm + wB · B_norm + wC · C_norm + wD · D_norm\n"
        "dove i pesi default sono wA = 0.40, wB = 0.25, wC = 0.20, wD = 0.15. "
        "I pesi sono configurabili nella dashboard per analisi di sensitività."
    ))

    _p(doc, (
        "I siti vengono classificati in 5 fasce di priorità basate sui percentili dell'ICP:\n"
        "• Monitoraggio (< 20° percentile)\n"
        "• Bassa (20°–40° percentile)\n"
        "• Media (40°–60° percentile)\n"
        "• Alta (60°–80° percentile)\n"
        "• Altissima (> 80° percentile)"
    ))

    doc.add_heading("2.5.4. Matrice di rischio", level=3)
    _p(doc, (
        "Oltre alla classifica ICP, i siti vengono posizionati in una matrice di rischio 2×2 "
        "basata su due assi:\n"
        "• Asse X: eccesso di incidentalità (componente A grezza, alto/basso rispetto al "
        "75° percentile dei siti con almeno un incidente).\n"
        "• Asse Y: severità (componente B grezza, alto/basso rispetto al 75° percentile).\n"
        "I quattro quadranti identificano:\n"
        "• Q1 – Intervento urgente: alto eccesso e alta severità.\n"
        "• Q2 – Intervento programmato: alto eccesso ma severità contenuta.\n"
        "• Q3 – Indagine approfondita: eccesso contenuto ma alta severità.\n"
        "• Q4 – Monitoraggio: entrambi i valori sotto soglia."
    ))

    _p(doc, (
        "Le soglie vengono calcolate esclusivamente sui siti con almeno un incidente, "
        "per evitare che la massa di siti a zero incidenti abbassi artificialmente le soglie."
    ))

    # ========== 2.6 FASE 5 ==========
    doc.add_heading("2.6. Fase 5 – Export e dashboard interattiva", level=2)

    _p(doc, (
        "I risultati vengono esportati in diversi formati:\n"
        "• GeoJSON per la visualizzazione cartografica nella dashboard (WGS84).\n"
        "• Excel con la classifica completa dei siti ordinati per ICP decrescente, "
        "separatamente per segmenti e intersezioni.\n"
        "• Mappa statica PNG con i siti colorati per fascia di priorità.\n"
        "• CSV di sintesi aggregata per fascia e tipo di sito."
    ))

    _p(doc, (
        "La dashboard interattiva, sviluppata in Dash/Plotly, consente:\n"
        "• Mappa interattiva con i siti colorati per intensità dell'ICP (gradiente "
        "giallo-arancione-rosso), con filtri per tipo di sito, fascia di priorità "
        "e numero di siti da visualizzare (top N per ICP).\n"
        "• Pannello di dettaglio per il sito selezionato: radar delle 4 componenti, "
        "distribuzione per gravità, indicatori sintetici.\n"
        "• Tab diagnostica SPF: scatter O vs E, residui di Pearson, istogramma incidenti, "
        "riepilogo dei modelli calibrati per categoria.\n"
        "• Tab diagnostica EB: distribuzioni dell'eccesso, del peso EB, classifica "
        "per excess_EPDO.\n"
        "• Tab analisi di sensitività: variazione dei pesi A/B/C/D con ricalcolo in tempo "
        "reale dell'ICP, correlazione di Spearman con la classifica default, confronto "
        "dei top 20 siti.\n"
        "• Tab vista decisionale: matrice di rischio interattiva, distribuzione per fasce, "
        "classifica dei top 20 segmenti e top 20 intersezioni reattiva ai pesi configurati."
    ))

    # ========== 3. RIFERIMENTI BIBLIOGRAFICI ==========
    doc.add_heading("3. Riferimenti bibliografici", level=1)

    refs = [
        "AASHTO (2010). Highway Safety Manual, 1st Edition. American Association of State "
        "Highway and Transportation Officials, Washington, D.C.",

        "Cameron, A.C. e Trivedi, P.K. (1998). Regression Analysis of Count Data. "
        "Cambridge University Press.",

        "Direttiva 2008/96/CE del Parlamento europeo e del Consiglio sulla gestione della "
        "sicurezza delle infrastrutture stradali. Gazzetta ufficiale dell’Unione europea, "
        "L 319/59.",

        "Direttiva (UE) 2019/1936 che modifica la direttiva 2008/96/CE sulla gestione della "
        "sicurezza delle infrastrutture stradali. Gazzetta ufficiale dell’Unione europea, "
        "L 305/1.",

        "Hauer, E. (1997). Observational Before-After Studies in Road Safety. "
        "Pergamon Press, Oxford.",

        "Hauer, E., Harwood, D.W., Council, F.M. e Griffith, M.S. (2002). Estimating safety "
        "by the empirical Bayes method: a tutorial. Transportation Research Record, 1784(1), "
        "pp. 126–131.",

        "La Torre, F., Domenichini, L. e Corsi, F. (2019). A comparative analysis of "
        "network-level road safety screening methods. Accident Analysis & Prevention, 130, "
        "pp. 272–281.",

        "Montella, A. (2010). A comparative analysis of hotspot identification methods. "
        "Accident Analysis & Prevention, 42(2), pp. 571–581.",

        "Persaud, B., Lyon, C. e Nguyen, T. (1999). Empirical Bayes procedure for ranking "
        "sites for safety investigation by potential for safety improvement. "
        "Transportation Research Record, 1665(1), pp. 7–12.",

        "MEF/ISTAT (2022). Valori monetari della sicurezza stradale – Costi sociali degli "
        "incidenti stradali. Nota metodologica, Roma.",
    ]
    for ref in refs:
        p = doc.add_paragraph(ref, style="List Bullet")
        p.paragraph_format.space_after = Pt(4)

    # ========== 4. LIMITI E SVILUPPI FUTURI ==========
    doc.add_heading("4. Limiti del prototipo e sviluppi futuri", level=1)

    _p(doc, (
        "Il sistema qui presentato costituisce un prototipo funzionante che dimostra la "
        "fattibilità dell'approccio e produce risultati già utilizzabili per una prima "
        "individuazione delle criticità della rete. Tuttavia, la qualità dei risultati finali "
        "dipende in misura determinante dalla qualità dei dati di input, e in questo senso "
        "diversi aspetti richiedono attenzione prima che il sistema possa essere adottato come "
        "strumento decisionale operativo."
    ), bold=False, italic=False)

    doc.add_heading("4.1. Qualità dei dati incidentali: il nodo critico", level=2)
    _p(doc, (
        "La criticità principale riguarda il database incidentale del Comune di Roma. "
        "Allo stato attuale:\n"
        "• Il dataset storico (Incidenti_1) copre il periodo 2004–2022 ma la geocodifica "
        "degli incidenti pre-2018 presenta imprecisioni significative e non è ancora stata "
        "oggetto di una campagna di rigeolocalizzazione sistematica.\n"
        "• Le rigeolocalizzazioni annuali (2022, 2023, 2024) migliorano la precisione ma "
        "coprono solo una parte del periodo. Gli incidenti non rigeolocalizzati hanno il "
        "campo id_ta1 nullo (non agganciati alla rete TomTom) e dipendono interamente dal "
        "matching spaziale/toponomastico di Fase 1, con un tasso inevitabile di errori.\n"
        "• Non è disponibile una distinzione affidabile tra feriti gravi e feriti lievi: "
        "il sistema è costretto a trattare tutti i feriti come un'unica categoria, perdendo "
        "informazione preziosa per la valutazione della severità.\n"
        "• Il campo «natura dell'incidente» (tipologia: investimento pedonale, scontro frontale, "
        "tamponamento, ecc.) è presente ma non sempre compilato in modo omogeneo, limitando "
        "l'affidabilità della componente C (vulnerabilità pedoni)."
    ))

    _p(doc, (
        "Senza un aggiornamento e una correzione sistematica dei dati incidentali, "
        "non è possibile ottenere una calibrazione accurata dei modelli SPF né una "
        "definizione affidabile delle priorità dei black point. Questo punto è "
        "il prerequisito fondamentale per qualsiasi sviluppo futuro del sistema."
    ), bold=True)

    doc.add_heading("4.2. Proposte di sviluppo e miglioramento", level=2)
    _p(doc, (
        "Riconoscendo la natura prototipale del sistema, si indicano le seguenti direttrici "
        "di sviluppo, suddivise tra interventi sui dati e interventi metodologici."
    ))

    _p(doc, (
        "Interventi prioritari sui dati:\n"
        "• Rigeolocalizzazione sistematica di tutti gli incidenti del periodo 2010–2024, "
        "con aggancio diretto alla rete TomTom (popolamento dei campi id_ta1/id_mnet1).\n"
        "• Introduzione della distinzione feriti gravi / feriti lievi nel flusso di "
        "registrazione degli incidenti (conforme alla definizione del Codice della Strada e "
        "alle convenzioni ISTAT).\n"
        "• Bonifica del campo «natura dell'incidente» e della classificazione per tipo di "
        "utente coinvolto (pedone, ciclista, motociclista).\n"
        "• Aggiornamento periodico della rete TomTom e dei dati di traffico/velocità."
    ))

    _p(doc, (
        "Miglioramenti metodologici:\n"
        "• Calibrazione di modelli SPF stratificati per periodo temporale (pre/post COVID, "
        "pre/post interventi infrastrutturali) per catturare trend e discontinuità.\n"
        "• Introduzione di modelli a effetti misti (random effects) per catturare l'eterogeneità "
        "spaziale non osservata.\n"
        "• Integrazione di covariate aggiuntive: caratteristiche della sezione trasversale "
        "(numero di corsie, presenza di spartitraffico, pista ciclabile), vicinanza a poli "
        "attrattori (scuole, ospedali, centri commerciali), illuminazione.\n"
        "• Analisi di sensitività strutturata sui pesi dell'ICP, con validazione rispetto "
        "a benchmark esterni (siti già noti come critici dalle Forze di Polizia).\n"
        "• Estensione dell'analisi ai ciclisti come categoria dedicata di utenti vulnerabili.\n"
        "• Implementazione di un modulo Before–After per la valutazione dell'efficacia degli "
        "interventi di messa in sicurezza già realizzati.\n"
        "• Generazione automatica di schede-sito per i black point prioritari, con "
        "cartografia di dettaglio, pin diagrams e suggerimenti di contromisure."
    ))

    doc.add_heading("4.3. Considerazioni finali", level=2)
    _p(doc, (
        "Il prototipo dimostra che l'approccio EB con indice composito multi-criterio è "
        "applicabile alla rete stradale di Roma e produce risultati coerenti con la letteratura "
        "e con l'esperienza sul campo. La pipeline è completamente automatizzata, riproducibile "
        "e aggiornabile al rilascio di nuovi dati. Tuttavia, la bontà dei risultati è "
        "intrinsecamente legata alla qualità dei dati incidentali: nessun modello statistico "
        "può compensare un dato di input sistematicamente incompleto o impreciso."
    ))

    _p(doc, (
        "Si raccomanda pertanto di subordinare l'adozione operativa del sistema a un "
        "investimento strutturale nella qualità dei dati incidentali, senza il quale "
        "le priorità individuate restano indicative ma non possono essere considerate "
        "definitive."
    ), bold=True)

    # ========== SALVATAGGIO ==========
    out = Path(__file__).resolve().parent / "relazione_metodologica.docx"
    doc.save(str(out))
    print(f"Relazione salvata: {out}")


if __name__ == "__main__":
    genera()
