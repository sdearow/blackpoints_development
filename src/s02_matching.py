"""Step 02 - Matching spaziale incidenti <-> rete (Fase 1).

Estrae le intersezioni dai nodi della rete TomTom, costruisce i segmenti
omogenei tra intersezioni e assegna ogni incidente a un'intersezione o a un
segmento secondo i criteri descritti nel Task 1.2/1.3 del piano.

Il modulo e' organizzato in tre blocchi logici:

1. **Task 1.1a (questo commit)** - Estrazione delle intersezioni dai nodi
   della rete TomTom e associazione degli impianti semaforici. Output:
   ``data/interim/intersezioni.gpkg``.
2. **Task 1.1b** - Costruzione dei segmenti omogenei per toponimo e
   topologia, spezzati alle intersezioni e dove il TGM varia oltre soglia.
   Output: ``data/interim/segmenti.gpkg``.
3. **Task 1.2 + 1.3** - Snap incidenti a intersezione/segmento con fallback
   toponomastico fuzzy. Output: ``data/interim/incidenti_matched.gpkg``.

Conventione: tutti i calcoli geometrici avvengono nel CRS metrico di
lavoro (``EPSG:32633``), coerentemente con l'output di s01.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point

from src.config import RADICE_PROGETTO, carica_config

log = logging.getLogger("s02_matching")


# ---------------------------------------------------------------------------
# Estrazione endpoint degli archi
# ---------------------------------------------------------------------------


def _endpoint_linea(geom: Any) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Restituisce ``((x_start, y_start), (x_end, y_end))`` per una geometria lineare.

    Supporta ``LineString`` e ``MultiLineString``: in quest'ultimo caso
    prende il primo vertice della prima sottolinea e l'ultimo vertice
    dell'ultima sottolinea (la rete TomTom e' orientata e connessa, quindi
    questi sono gli endpoint reali dell'arco).
    """
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, LineString):
        coords = list(geom.coords)
    elif isinstance(geom, MultiLineString):
        parti = list(geom.geoms)
        if not parti:
            return None
        coords_inizio = list(parti[0].coords)
        coords_fine = list(parti[-1].coords)
        if not coords_inizio or not coords_fine:
            return None
        return (
            (coords_inizio[0][0], coords_inizio[0][1]),
            (coords_fine[-1][0], coords_fine[-1][1]),
        )
    else:
        return None

    if not coords:
        return None
    return (
        (coords[0][0], coords[0][1]),
        (coords[-1][0], coords[-1][1]),
    )


def estrai_endpoint_archi(gdf_rete: gpd.GeoDataFrame) -> pd.DataFrame:
    """Estrae due righe per arco (endpoint ``start`` e ``end``).

    Colonne restituite: ``id_arco``, ``posizione`` (``start``/``end``),
    ``x``, ``y``. Gli archi con geometria nulla/vuota vengono saltati.
    """
    if "id_arco" not in gdf_rete.columns:
        raise KeyError("gdf_rete deve contenere la colonna 'id_arco'")

    records: list[tuple[int, str, float, float]] = []
    for id_arco, geom in zip(gdf_rete["id_arco"].values, gdf_rete.geometry.values):
        endpoints = _endpoint_linea(geom)
        if endpoints is None:
            continue
        (x_s, y_s), (x_e, y_e) = endpoints
        records.append((id_arco, "start", x_s, y_s))
        records.append((id_arco, "end", x_e, y_e))

    return pd.DataFrame.from_records(
        records, columns=["id_arco", "posizione", "x", "y"]
    )


# ---------------------------------------------------------------------------
# Clustering degli endpoint -> nodi
# ---------------------------------------------------------------------------


def _assegna_id_nodo_per_griglia(
    df_endpoint: pd.DataFrame, tolleranza_m: float
) -> pd.Series:
    """Assegna ``id_nodo`` clusterizzando endpoint entro ``tolleranza_m``.

    Usa un cKDTree per trovare tutte le coppie di endpoint a distanza
    inferiore alla tolleranza e una union-find per propagare l'id di
    cluster lungo le componenti connesse. Per reti topologicamente sane
    (TomTom) in cui i nodi condivisi hanno coordinate identiche, il
    risultato coincide con il raggruppamento esatto; il KDTree gestisce
    correttamente anche piccoli disallineamenti entro tolleranza.
    """
    from scipy.spatial import cKDTree

    n = len(df_endpoint)
    if n == 0:
        return pd.Series([], index=df_endpoint.index, dtype="int64")

    xy = np.column_stack(
        [df_endpoint["x"].to_numpy(dtype=float), df_endpoint["y"].to_numpy(dtype=float)]
    )
    albero = cKDTree(xy)
    coppie = albero.query_pairs(r=float(tolleranza_m), output_type="ndarray")

    parent = np.arange(n, dtype=np.int64)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            if ri < rj:
                parent[rj] = ri
            else:
                parent[ri] = rj

    for i, j in coppie:
        union(int(i), int(j))

    radici = np.array([find(i) for i in range(n)], dtype=np.int64)
    # Rinumera in id_nodo densi e stabili (ordinati per prima occorrenza).
    _, id_nodo = np.unique(radici, return_inverse=True)
    return pd.Series(id_nodo.astype("int64"), index=df_endpoint.index)


def costruisci_nodi(
    df_endpoint: pd.DataFrame,
    tolleranza_m: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Dal dataframe degli endpoint costruisce nodi e mapping arco<->nodo.

    Restituisce:
    - ``df_nodi``: dataframe con ``id_nodo``, ``x``, ``y``, ``n_archi``,
      dove le coordinate sono il baricentro del cluster e ``n_archi`` e'
      il numero di archi distinti che convergono al nodo.
    - ``df_archi_nodi``: mapping ``id_arco -> (id_nodo_start, id_nodo_end)``.
    """
    df_endpoint = df_endpoint.copy()
    df_endpoint["id_nodo"] = _assegna_id_nodo_per_griglia(df_endpoint, tolleranza_m)

    df_nodi = (
        df_endpoint.groupby("id_nodo", as_index=False)
        .agg(
            x=("x", "mean"),
            y=("y", "mean"),
            n_archi=("id_arco", "nunique"),
        )
    )

    # Mapping arco -> nodo_start / nodo_end (pivot sulla colonna 'posizione').
    df_archi_nodi = (
        df_endpoint.pivot_table(
            index="id_arco",
            columns="posizione",
            values="id_nodo",
            aggfunc="first",
        )
        .rename(columns={"start": "id_nodo_start", "end": "id_nodo_end"})
        .reset_index()
    )

    # Pivot table puo' generare colonne con nome NaN se mancano posizioni;
    # in condizioni sane arrivano sempre 'start' e 'end'.
    return df_nodi, df_archi_nodi


# ---------------------------------------------------------------------------
# Estrazione delle intersezioni
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Etichettatura toponomastica delle intersezioni
# ---------------------------------------------------------------------------

# Pattern dei toponimi "di piazza": vanno in testa al label di un'intersezione
# perche' identificano lo slargo/spazio nodale piuttosto che le strade afferenti.
_PRIORITA_TOPO_PATTERN = re.compile(
    r"^\s*(piazza|p\.zza|p\.za|piazzale|p\.le|largo|l\.go|slargo|rotonda|belvedere|piazzetta)\b",
    re.IGNORECASE,
)


def _ordina_toponimi_intersezione(toponimi: list[str]) -> list[str]:
    """Ordina i toponimi mettendo piazza/largo/piazzale/ecc. davanti.

    All'interno di ciascun gruppo (priorita' o ordinari) i toponimi sono
    ordinati alfabeticamente per riproducibilita'.
    """
    visti: set[str] = set()
    distinti: list[str] = []
    for t in toponimi:
        if not isinstance(t, str):
            continue
        chiave = t.strip()
        if not chiave or chiave.lower() in visti:
            continue
        visti.add(chiave.lower())
        distinti.append(chiave)
    chiave_ord = lambda s: s.lower()  # noqa: E731
    priori = sorted(
        (t for t in distinti if _PRIORITA_TOPO_PATTERN.match(t)),
        key=chiave_ord,
    )
    altri = sorted(
        (t for t in distinti if not _PRIORITA_TOPO_PATTERN.match(t)),
        key=chiave_ord,
    )
    return priori + altri


def _calcola_toponimi_intersezioni_buffer(
    gdf_intersezioni: gpd.GeoDataFrame,
    gdf_rete: gpd.GeoDataFrame,
    raggio_m: float,
) -> pd.Series:
    """Per ogni intersezione, restituisce la lista ordinata di toponimi degli
    archi TomTom che intersecano un buffer di ``raggio_m`` metri attorno
    al nodo. I toponimi sono ordinati con piazza/largo/ecc. in testa.
    """
    if "toponimo" not in gdf_rete.columns or len(gdf_intersezioni) == 0:
        return pd.Series(
            [[] for _ in range(len(gdf_intersezioni))],
            index=gdf_intersezioni.index,
        )

    # Buffer poligonali attorno ai nodi.
    geom_buffer = gdf_intersezioni.geometry.buffer(float(raggio_m))
    buffers = gpd.GeoDataFrame(
        {"id_nodo": gdf_intersezioni["id_nodo"].values},
        geometry=geom_buffer.values,
        crs=gdf_intersezioni.crs,
    )

    rete_subset = gdf_rete[["toponimo", "geometry"]].copy()
    # Spatial join: archi che intersecano i buffer.
    joined = gpd.sjoin(
        rete_subset, buffers, how="inner", predicate="intersects"
    )

    if len(joined) == 0:
        return pd.Series(
            [[] for _ in range(len(gdf_intersezioni))],
            index=gdf_intersezioni.index,
        )

    # Per ogni nodo, raccogli i toponimi distinti ordinati con priorita'.
    toponimi_per_nodo = (
        joined.dropna(subset=["toponimo"])
        .groupby("id_nodo")["toponimo"]
        .apply(lambda s: _ordina_toponimi_intersezione(list(s)))
    )

    return gdf_intersezioni["id_nodo"].map(toponimi_per_nodo).apply(
        lambda v: v if isinstance(v, list) else []
    )


def _label_intersezione(toponimi: list[str], max_componenti: int = 3) -> str | None:
    """Costruisce un'etichetta testuale per l'intersezione a partire dalla
    lista (ordinata) di toponimi: i primi ``max_componenti`` uniti da ' / '.
    """
    if not toponimi:
        return None
    return " / ".join(toponimi[:max_componenti])


def arricchisci_toponimi_intersezioni(
    gdf_intersezioni: gpd.GeoDataFrame,
    gdf_rete: gpd.GeoDataFrame,
    raggio_m: float = 20.0,
    max_componenti_label: int = 3,
) -> gpd.GeoDataFrame:
    """Aggiunge ``toponimi_buffer`` (lista) e ``toponimo`` (label) alle
    intersezioni, derivati dagli archi TomTom che intersecano un buffer
    attorno al nodo. I toponimi tipo Piazza/Largo/ecc. vengono in testa.
    """
    gdf = gdf_intersezioni.copy()
    toponimi_buffer = _calcola_toponimi_intersezioni_buffer(
        gdf, gdf_rete, raggio_m
    )
    gdf["toponimi_buffer"] = toponimi_buffer
    gdf["toponimo"] = toponimi_buffer.apply(
        lambda lst: _label_intersezione(lst, max_componenti=max_componenti_label)
    )
    return gdf


def estrai_intersezioni(
    gdf_rete: gpd.GeoDataFrame,
    tolleranza_m: float = 0.5,
    filtra_falsi_incroci: bool = True,
    raggio_cluster_intersezioni_m: float = 30.0,
    raggio_toponimi_m: float = 20.0,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Estrae i nodi-intersezione della rete TomTom.

    Un nodo e' considerato intersezione se ``n_archi >= 3`` (almeno tre
    archi distinti convergono al punto). Nodi a grado 1 (dead-end) e a
    grado 2 (continuazione di strada) non vengono classificati come
    intersezioni.

    Restituisce:
    - ``gdf_intersezioni``: GeoDataFrame con ``id_nodo``, ``n_archi``,
      ``archi`` (lista id_arco), ``toponimi`` (lista toponimi distinti),
      geometria ``Point``, stesso CRS della rete.
    - ``df_archi_nodi``: mapping completo arco -> nodo_start/nodo_end
      (serve alla segmentazione e al matching per ricostruire il grafo).
    """
    if gdf_rete.crs is None:
        raise ValueError("gdf_rete deve avere un CRS definito")

    log.info(
        "Estrazione intersezioni da %d archi (tolleranza nodo = %.2f m)",
        len(gdf_rete),
        tolleranza_m,
    )
    df_endpoint = estrai_endpoint_archi(gdf_rete)
    df_nodi, df_archi_nodi = costruisci_nodi(df_endpoint, tolleranza_m=tolleranza_m)

    log.info(
        "Trovati %d nodi distinti (tra cui %d di grado 1, %d di grado 2, "
        "%d di grado >=3)",
        len(df_nodi),
        int((df_nodi["n_archi"] == 1).sum()),
        int((df_nodi["n_archi"] == 2).sum()),
        int((df_nodi["n_archi"] >= 3).sum()),
    )

    df_intersezioni = df_nodi.loc[df_nodi["n_archi"] >= 3].copy()

    # Aggrega gli archi per nodo a partire da df_archi_nodi: per ogni
    # id_nodo prendiamo gli archi che hanno quel nodo come start o come end.
    df_lungo = pd.concat(
        [
            df_archi_nodi[["id_arco", "id_nodo_start"]].rename(
                columns={"id_nodo_start": "id_nodo"}
            ),
            df_archi_nodi[["id_arco", "id_nodo_end"]].rename(
                columns={"id_nodo_end": "id_nodo"}
            ),
        ],
        ignore_index=True,
    )
    id_nodi_intersezione = set(df_intersezioni["id_nodo"].tolist())
    df_lungo = df_lungo.loc[df_lungo["id_nodo"].isin(id_nodi_intersezione)]
    lista_archi = (
        df_lungo.groupby("id_nodo")["id_arco"]
        .apply(lambda s: sorted(set(int(v) for v in s)))
        .rename("archi")
    )

    toponimo_per_arco = {}
    if "toponimo" in gdf_rete.columns and "id_arco" in gdf_rete.columns:
        toponimo_per_arco = dict(
            zip(gdf_rete["id_arco"].values, gdf_rete["toponimo"].values)
        )

    def _toponimi_per_nodo(archi: list[int]) -> list[str]:
        topi = {
            toponimo_per_arco.get(a)
            for a in archi
            if toponimo_per_arco.get(a) is not None
            and not (isinstance(toponimo_per_arco.get(a), float) and pd.isna(toponimo_per_arco.get(a)))
        }
        return sorted(t for t in topi if isinstance(t, str) and t)

    df_intersezioni = df_intersezioni.merge(
        lista_archi, left_on="id_nodo", right_index=True, how="left"
    )
    df_intersezioni["toponimi"] = df_intersezioni["archi"].apply(_toponimi_per_nodo)

    geometry = [Point(x, y) for x, y in zip(df_intersezioni["x"], df_intersezioni["y"])]
    gdf_intersezioni = gpd.GeoDataFrame(
        df_intersezioni.drop(columns=["x", "y"]),
        geometry=geometry,
        crs=gdf_rete.crs,
    )

    if filtra_falsi_incroci:
        gdf_intersezioni = _filtra_falsi_incroci(
            gdf_intersezioni, gdf_rete,
            raggio_cluster_m=raggio_cluster_intersezioni_m,
        )

    # Etichettatura toponomastica: usa un buffer attorno al nodo per
    # catturare anche gli archi di una piazza/largo che non condividono
    # endpoint con tutte le strade afferenti.
    gdf_intersezioni = arricchisci_toponimi_intersezioni(
        gdf_intersezioni, gdf_rete, raggio_m=raggio_toponimi_m,
    )
    n_etichettati = int(gdf_intersezioni["toponimo"].notna().sum())
    log.info(
        "Etichettate %d/%d intersezioni con toponimo (buffer = %.1f m)",
        n_etichettati, len(gdf_intersezioni), raggio_toponimi_m,
    )

    return gdf_intersezioni, df_archi_nodi


def _filtra_falsi_incroci(
    gdf_intersezioni: gpd.GeoDataFrame,
    gdf_rete: gpd.GeoDataFrame,
    raggio_cluster_m: float = 30.0,
) -> gpd.GeoDataFrame:
    """Filtra le false intersezioni con tre criteri progressivi.

    1. **Mono-toponimo**: nodi a grado 3 o 4 con un solo toponimo distinto
       (confluenze di carreggiate separate, non veri incroci).
    2. **FRC uniforme**: nodi a grado 3 o 4 dove tutti gli archi hanno la
       stessa ``classe_frc`` e un solo toponimo (strada che si biforca e
       rientra senza cambiare classe).
    3. **Cluster di prossimita'**: nodi entro ``raggio_cluster_m`` che
       condividono lo stesso set di toponimi vengono fusi in un unico nodo
       (il baricentro del cluster), eliminando le false intersezioni
       intermedie generate da micro-segmentazioni della rete.
    """
    n_prima = len(gdf_intersezioni)

    # --- Filtro 1: mono-toponimo per grado 3 e 4 ---
    n_topo = gdf_intersezioni["toponimi"].apply(len)
    mask_falso_mono = (
        gdf_intersezioni["n_archi"].isin([3, 4]) & (n_topo <= 1)
    )
    n_mono = int(mask_falso_mono.sum())
    gdf_intersezioni = gdf_intersezioni.loc[~mask_falso_mono].copy()
    log.info(
        "Filtro mono-toponimo: %d false intersezioni rimosse su %d candidati "
        "(grado 3-4, <=1 toponimo distinto). Restano %d.",
        n_mono, n_prima, len(gdf_intersezioni),
    )

    # --- Filtro 2: FRC uniforme (grado 3-4, 1 solo FRC, <=2 toponimi) ---
    if "classe_frc" in gdf_rete.columns and "id_arco" in gdf_rete.columns:
        frc_per_arco = dict(
            zip(gdf_rete["id_arco"].values, gdf_rete["classe_frc"].values)
        )

        def _frc_uniformi(archi: list[int]) -> bool:
            frcs = {
                frc_per_arco.get(a)
                for a in archi
                if frc_per_arco.get(a) is not None
                and not (isinstance(frc_per_arco.get(a), float) and pd.isna(frc_per_arco.get(a)))
            }
            return len(frcs) == 1

        n_pre_frc = len(gdf_intersezioni)
        mask_frc = (
            gdf_intersezioni["n_archi"].isin([3, 4])
            & (gdf_intersezioni["toponimi"].apply(len) <= 2)
            & gdf_intersezioni["archi"].apply(_frc_uniformi)
        )
        n_frc = int(mask_frc.sum())
        gdf_intersezioni = gdf_intersezioni.loc[~mask_frc].copy()
        log.info(
            "Filtro FRC uniforme: %d false intersezioni rimosse su %d "
            "(grado 3-4, FRC unica, <=2 toponimi). Restano %d.",
            n_frc, n_pre_frc, len(gdf_intersezioni),
        )

    # --- Filtro 3: cluster di prossimita' ---
    if len(gdf_intersezioni) > 1 and raggio_cluster_m > 0:
        gdf_intersezioni = _cluster_intersezioni_vicine(
            gdf_intersezioni, raggio_cluster_m,
        )

    log.info(
        "Filtro falsi incroci completato: %d -> %d intersezioni.",
        n_prima, len(gdf_intersezioni),
    )
    return gdf_intersezioni


def _cluster_intersezioni_vicine(
    gdf: gpd.GeoDataFrame,
    raggio_m: float,
) -> gpd.GeoDataFrame:
    """Fonde intersezioni vicine con toponimi sovrapposti.

    Nodi entro ``raggio_m`` che condividono almeno un toponimo vengono
    raggruppati. Per ogni cluster si tiene il nodo con il grado piu' alto
    (piu' archi convergenti) come rappresentante, spostandone la geometria
    al baricentro del cluster. Gli altri nodi del cluster vengono rimossi.
    """
    from scipy.spatial import cKDTree

    coords = np.column_stack([gdf.geometry.x.to_numpy(), gdf.geometry.y.to_numpy()])
    tree = cKDTree(coords)
    coppie = tree.query_pairs(r=float(raggio_m), output_type="ndarray")

    if len(coppie) == 0:
        return gdf

    topo_sets = [set(t) for t in gdf["toponimi"].values]
    idx_array = gdf.index.to_numpy()

    n = len(gdf)
    parent = np.arange(n, dtype=np.int64)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    for i, j in coppie:
        if topo_sets[i] & topo_sets[j]:
            union(int(i), int(j))

    cluster_ids = np.array([find(i) for i in range(n)], dtype=np.int64)
    _, cluster_labels = np.unique(cluster_ids, return_inverse=True)

    n_archi_vals = gdf["n_archi"].to_numpy()
    keep_mask = np.zeros(n, dtype=bool)

    for cl in range(cluster_labels.max() + 1):
        membri = np.where(cluster_labels == cl)[0]
        if len(membri) == 1:
            keep_mask[membri[0]] = True
            continue
        rappresentante = membri[np.argmax(n_archi_vals[membri])]
        keep_mask[rappresentante] = True
        cx = coords[membri, 0].mean()
        cy = coords[membri, 1].mean()
        real_idx = idx_array[rappresentante]
        gdf.at[real_idx, "geometry"] = Point(cx, cy)
        merged_topo = set()
        merged_archi = set()
        for m in membri:
            merged_topo.update(topo_sets[m])
            merged_archi.update(gdf.at[idx_array[m], "archi"])
        gdf.at[real_idx, "toponimi"] = sorted(merged_topo)
        gdf.at[real_idx, "archi"] = sorted(merged_archi)
        gdf.at[real_idx, "n_archi"] = len(merged_archi)

    n_rimossi = int((~keep_mask).sum())
    n_cluster_multi = int((np.bincount(cluster_labels) > 1).sum())
    gdf = gdf.loc[idx_array[keep_mask]].copy()
    log.info(
        "Cluster prossimita' (raggio=%.0f m): %d cluster con >1 nodo, "
        "%d nodi ridondanti rimossi. Restano %d.",
        raggio_m, n_cluster_multi, n_rimossi, len(gdf),
    )
    return gdf


# ---------------------------------------------------------------------------
# Associazione semafori -> intersezioni
# ---------------------------------------------------------------------------


def associa_semafori(
    gdf_intersezioni: gpd.GeoDataFrame,
    gdf_semafori: gpd.GeoDataFrame,
    raggio_m: float,
    raggio_max_m: float | None = 100.0,
) -> gpd.GeoDataFrame:
    """Associa ogni semaforo veicolare al nodo-intersezione piu' vicino.

    Strategia:
    - ogni semaforo ``is_veicolare`` viene associato al nodo piu' vicino;
    - oltre ``raggio_m`` (soglia attesa) l'associazione viene loggata
      come warning ma mantenuta;
    - oltre ``raggio_max_m`` (tetto, default 100 m) l'associazione viene
      SCARTATA: un semaforo a centinaia di metri non semaforizza un
      incrocio - nel dato reale si osservavano associazioni fino a
      1.554 m che misclassificavano nodi nella SPF 'semaforizzata'.
      ``raggio_max_m=None`` ripristina il comportamento senza tetto
      (la vecchia "scelta C");
    - un nodo e' ``is_semaforizzata`` se almeno un semaforo veicolare
      gli e' stato associato.

    Nuove colonne aggiunte a ``gdf_intersezioni``:
    - ``is_semaforizzata``: boolean
    - ``n_semafori``: int, numero di impianti veicolari associati
    - ``id_impianti``: lista di ``id_impianto`` associati (puo' essere vuota)
    """
    if gdf_intersezioni.crs is None or gdf_semafori.crs is None:
        raise ValueError("Entrambi i GeoDataFrame devono avere CRS definito")
    if gdf_semafori.crs != gdf_intersezioni.crs:
        log.info(
            "Riproiezione semafori: %s -> %s",
            gdf_semafori.crs,
            gdf_intersezioni.crs,
        )
        gdf_semafori = gdf_semafori.to_crs(gdf_intersezioni.crs)

    # Filtra solo i semafori veicolari: i pedonali non definiscono
    # un'intersezione semaforizzata.
    if "is_veicolare" in gdf_semafori.columns:
        gdf_v = gdf_semafori.loc[gdf_semafori["is_veicolare"].fillna(False)].copy()
    else:
        gdf_v = gdf_semafori.copy()

    log.info(
        "Associa %d semafori veicolari a %d intersezioni (raggio soglia %.0f m)",
        len(gdf_v),
        len(gdf_intersezioni),
        raggio_m,
    )

    if len(gdf_v) == 0 or len(gdf_intersezioni) == 0:
        gdf_out = gdf_intersezioni.copy()
        gdf_out["is_semaforizzata"] = False
        gdf_out["n_semafori"] = 0
        gdf_out["id_impianti"] = [[] for _ in range(len(gdf_out))]
        return gdf_out

    # sjoin_nearest: per ogni semaforo trova l'intersezione piu' vicina.
    joined = gpd.sjoin_nearest(
        gdf_v[["id_impianto", "geometry"]],
        gdf_intersezioni[["id_nodo", "geometry"]],
        how="left",
        distance_col="distanza_m",
    )

    # Tetto: le associazioni oltre raggio_max_m vengono scartate.
    if raggio_max_m is not None:
        fuori = joined["distanza_m"] > float(raggio_max_m)
        if fuori.any():
            log.warning(
                "Semafori scartati oltre il tetto di %.0f m: %d "
                "(max %.1f m, mediana %.1f m)",
                raggio_max_m,
                int(fuori.sum()),
                float(joined.loc[fuori, "distanza_m"].max()),
                float(joined.loc[fuori, "distanza_m"].median()),
            )
            joined = joined.loc[~fuori]

    # Log di warning per i semafori oltre soglia attesa (entro il tetto).
    oltre = joined.loc[joined["distanza_m"] > raggio_m]
    if len(oltre) > 0:
        log.warning(
            "Semafori associati oltre %.0f m: %d (max %.1f m, mediana %.1f m)",
            raggio_m,
            len(oltre),
            float(oltre["distanza_m"].max()),
            float(oltre["distanza_m"].median()),
        )

    # Aggrega per id_nodo.
    per_nodo = (
        joined.dropna(subset=["id_nodo"])
        .groupby("id_nodo")
        .agg(
            n_semafori=("id_impianto", "nunique"),
            id_impianti=("id_impianto", lambda s: sorted(set(s.tolist()))),
        )
    )

    gdf_out = gdf_intersezioni.merge(per_nodo, left_on="id_nodo", right_index=True, how="left")
    gdf_out["n_semafori"] = gdf_out["n_semafori"].fillna(0).astype(int)
    gdf_out["id_impianti"] = gdf_out["id_impianti"].apply(
        lambda v: v if isinstance(v, list) else []
    )
    gdf_out["is_semaforizzata"] = gdf_out["n_semafori"] > 0

    n_sem_tot = int(gdf_out["is_semaforizzata"].sum())
    log.info(
        "Intersezioni semaforizzate: %d / %d (%.1f%%)",
        n_sem_tot,
        len(gdf_out),
        100.0 * n_sem_tot / max(len(gdf_out), 1),
    )
    return gdf_out


# ---------------------------------------------------------------------------
# Riassunto e salvataggio
# ---------------------------------------------------------------------------


def riassumi_intersezioni(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Riassunto di qualita' del dataset delle intersezioni."""
    riassunto: dict[str, Any] = {
        "n_intersezioni": int(len(gdf)),
    }
    if "n_archi" in gdf.columns:
        riassunto["n_per_grado"] = (
            gdf["n_archi"].value_counts(dropna=False).sort_index().astype(int).to_dict()
        )
    if "is_semaforizzata" in gdf.columns:
        riassunto["n_semaforizzate"] = int(gdf["is_semaforizzata"].sum())
    if "n_semafori" in gdf.columns:
        riassunto["n_semafori_associati"] = int(gdf["n_semafori"].sum())
    return riassunto


def salva_intersezioni(gdf: gpd.GeoDataFrame, percorso: Path) -> None:
    """Salva il GeoDataFrame delle intersezioni in GeoPackage.

    Le colonne ``archi``, ``toponimi``, ``id_impianti`` sono liste Python
    che non possono essere serializzate come tali nel GPKG: le serializziamo
    come stringhe ``|``-separate (vuote per le liste vuote).
    """
    percorso.parent.mkdir(parents=True, exist_ok=True)
    if percorso.exists():
        percorso.unlink()

    gdf_out = gdf.copy()
    for col in ("archi", "toponimi", "toponimi_buffer", "id_impianti"):
        if col in gdf_out.columns:
            gdf_out[col] = gdf_out[col].apply(
                lambda lst: "|".join(str(x) for x in lst) if isinstance(lst, list) else ""
            )

    log.info("Salvataggio intersezioni: %s (%d record)", percorso, len(gdf_out))
    gdf_out.to_file(percorso, driver="GPKG", layer="intersezioni")


# ---------------------------------------------------------------------------
# Segmentazione omogenea (Task 1.1b)
# ---------------------------------------------------------------------------


def _norm_topo(toponimo: Any) -> str | None:
    """Normalizza il toponimo per il confronto in segmentazione.

    Usa ``normalizza_nome_strada`` di s00 (capitalizzazione standard) e
    ulteriormente normalizza spazi multipli, trattini/virgole come
    separatori e converte in minuscolo per il confronto.
    """
    from src.s00_pulizia_incidenti import normalizza_nome_strada

    norm = normalizza_nome_strada(toponimo)
    if norm is None:
        return None
    s = norm.lower()
    s = s.replace(",", " ").replace("-", " ")
    s = " ".join(s.split())
    return s if s else None


def _costruisci_indice_archi(
    gdf_rete: gpd.GeoDataFrame,
    df_archi_nodi: pd.DataFrame,
    df_nodi: pd.DataFrame,
) -> dict[str, Any]:
    """Costruisce gli indici utili alla segmentazione.

    Restituisce un dizionario con:
    - ``arco_endpoints``: ``id_arco -> (id_nodo_start, id_nodo_end)``
    - ``arco_topo``: ``id_arco -> toponimo normalizzato (str o None)``
    - ``arco_tgm``: ``id_arco -> tgm (float)``
    - ``arco_lung``: ``id_arco -> lunghezza_m (float)``
    - ``nodo_grado``: ``id_nodo -> n_archi``
    - ``nodo_archi``: ``id_nodo -> list[id_arco]``
    """
    arco_endpoints = {
        int(r.id_arco): (int(r.id_nodo_start), int(r.id_nodo_end))
        for r in df_archi_nodi.itertuples(index=False)
    }
    nodo_grado = {
        int(r.id_nodo): int(r.n_archi) for r in df_nodi.itertuples(index=False)
    }

    arco_topo: dict[int, str | None] = {}
    arco_tgm: dict[int, float] = {}
    arco_lung: dict[int, float] = {}
    for r in gdf_rete[["id_arco", "toponimo", "tgm", "lunghezza_m"]].itertuples(
        index=False
    ):
        ida = int(r.id_arco)
        arco_topo[ida] = _norm_topo(r.toponimo)
        arco_tgm[ida] = float(r.tgm) if r.tgm is not None and not pd.isna(r.tgm) else 0.0
        arco_lung[ida] = (
            float(r.lunghezza_m)
            if r.lunghezza_m is not None and not pd.isna(r.lunghezza_m)
            else 0.0
        )

    nodo_archi: dict[int, list[int]] = {}
    for ida, (a, b) in arco_endpoints.items():
        nodo_archi.setdefault(a, []).append(ida)
        nodo_archi.setdefault(b, []).append(ida)

    return {
        "arco_endpoints": arco_endpoints,
        "arco_topo": arco_topo,
        "arco_tgm": arco_tgm,
        "arco_lung": arco_lung,
        "nodo_grado": nodo_grado,
        "nodo_archi": nodo_archi,
    }


def _costruisci_catene(
    indice: dict[str, Any],
    soglia_var_tgm: float,
    id_nodi_intersezione: set[int] | None = None,
) -> list[list[int]]:
    """Costruisce le catene massimali di archi mergiabili.

    Le catene si interrompono alle intersezioni reali (``id_nodi_intersezione``),
    ai dead-end (grado 1), al cambio di toponimo e alla variazione di TGM
    oltre ``soglia_var_tgm``. Per nodi grado 3+ che NON sono intersezioni
    reali (es. confluenze carreggiate), la catena prosegue se esiste un unico
    arco candidato con lo stesso toponimo.
    """
    arco_endpoints = indice["arco_endpoints"]
    arco_topo = indice["arco_topo"]
    arco_tgm = indice["arco_tgm"]
    nodo_grado = indice["nodo_grado"]
    nodo_archi = indice["nodo_archi"]
    nodi_int = id_nodi_intersezione

    def _passabile(arco_corr: int, nodo: int) -> int | None:
        """Restituisce l'arco successivo attraverso ``nodo``, o None."""
        grado = nodo_grado.get(nodo, 0)
        if grado <= 1:
            return None

        if nodi_int is None:
            if grado != 2:
                return None
        else:
            if nodo in nodi_int:
                return None

        candidati = [a for a in nodo_archi[nodo] if a != arco_corr]
        topo_corr = arco_topo.get(arco_corr)

        if grado == 2:
            if len(candidati) != 1:
                return None
            prossimo = candidati[0]
            if topo_corr is None or arco_topo.get(prossimo) is None:
                return None
            if arco_topo[prossimo] != topo_corr:
                return None
        else:
            if topo_corr is None:
                return None
            stessi = [a for a in candidati if arco_topo.get(a) == topo_corr]
            if len(stessi) != 1:
                return None
            prossimo = stessi[0]

        tgm_a = arco_tgm[arco_corr]
        tgm_b = arco_tgm[prossimo]
        if tgm_a > 0 and tgm_b > 0:
            base = max(tgm_a, tgm_b)
            if abs(tgm_a - tgm_b) / base > soglia_var_tgm:
                return None
        return prossimo

    visitati: set[int] = set()
    catene: list[list[int]] = []

    for id_arco in arco_endpoints:
        if id_arco in visitati:
            continue
        catena = [id_arco]
        visitati.add(id_arco)

        # Estensione in avanti (lato 'end').
        prev = id_arco
        nodo_avanti = arco_endpoints[id_arco][1]
        while True:
            nxt = _passabile(prev, nodo_avanti)
            if nxt is None or nxt in visitati:
                break
            visitati.add(nxt)
            catena.append(nxt)
            ns, ne = arco_endpoints[nxt]
            nodo_avanti = ne if ns == nodo_avanti else ns
            prev = nxt

        # Estensione all'indietro (lato 'start').
        prev = id_arco
        nodo_indietro = arco_endpoints[id_arco][0]
        while True:
            nxt = _passabile(prev, nodo_indietro)
            if nxt is None or nxt in visitati:
                break
            visitati.add(nxt)
            catena.insert(0, nxt)
            ns, ne = arco_endpoints[nxt]
            nodo_indietro = ne if ns == nodo_indietro else ns
            prev = nxt

        catene.append(catena)

    return catene


def _spezza_per_lunghezza(
    catene: list[list[int]],
    arco_lung: dict[int, float],
    lung_max: float,
) -> list[list[int]]:
    """Spezza ogni catena in segmenti di lunghezza ``<= lung_max``.

    Se anche il singolo arco supera ``lung_max`` lo si lascia da solo
    (non spezziamo a meta' di un arco TomTom).
    """
    out: list[list[int]] = []
    for catena in catene:
        seg: list[int] = []
        l_seg = 0.0
        for ida in catena:
            l = arco_lung.get(ida, 0.0)
            if seg and l_seg + l > lung_max:
                out.append(seg)
                seg = []
                l_seg = 0.0
            seg.append(ida)
            l_seg += l
        if seg:
            out.append(seg)
    return out


def _estremi_catena(
    catena: list[int],
    arco_endpoints: dict[int, tuple[int, int]],
) -> tuple[int, int]:
    """Restituisce ``(id_nodo_start, id_nodo_end)`` di una catena ordinata."""
    if len(catena) == 1:
        return arco_endpoints[catena[0]]
    a0, a1 = catena[0], catena[1]
    s0, e0 = arco_endpoints[a0]
    s1, e1 = arco_endpoints[a1]
    # Il nodo condiviso e' quello "interno" tra a0 e a1: quindi il nodo
    # esterno di a0 e' quello che NON sta in a1.
    if s0 in (s1, e1):
        nodo_start = e0
    else:
        nodo_start = s0

    aN, aM = catena[-1], catena[-2]
    sN, eN = arco_endpoints[aN]
    sM, eM = arco_endpoints[aM]
    if sN in (sM, eM):
        nodo_end = eN
    else:
        nodo_end = sN
    return nodo_start, nodo_end


def _media_pesata(valori: np.ndarray, pesi: np.ndarray) -> float:
    """Media pesata robusta a NaN nei valori (i pesi associati vengono ignorati)."""
    mask = ~np.isnan(valori) & (pesi > 0)
    if not mask.any():
        return float("nan")
    return float(np.average(valori[mask], weights=pesi[mask]))


def _moda_categoriale(serie: pd.Series) -> Any:
    """Moda di una serie categoriale; ``None`` se vuota o tutti nulli."""
    s = serie.dropna()
    if s.empty:
        return None
    return s.mode().iloc[0]


def costruisci_segmenti(
    gdf_rete: gpd.GeoDataFrame,
    df_archi_nodi: pd.DataFrame,
    df_nodi: pd.DataFrame,
    soglia_var_tgm: float = 0.30,
    lung_min: float = 100.0,
    lung_max: float = 2000.0,
    id_nodi_intersezione: set[int] | None = None,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Costruisce i segmenti omogenei della rete (Task 1.1b).

    Algoritmo:

    1. Indicizza archi e nodi.
    2. Costruisce le catene massimali di archi consecutivi che condividono
       toponimo e che hanno variazione di TGM ``<= soglia_var_tgm``,
       interrompendole a tutte le intersezioni (nodi di grado >= 3).
    3. Spezza le catene troppo lunghe in segmenti di lunghezza
       ``<= lung_max``.
    4. Per ogni segmento aggrega gli attributi degli archi (medie pesate
       per lunghezza per le grandezze numeriche, moda per le categoriali)
       e marca come ``isolato`` i segmenti con lunghezza ``< lung_min``.

    Restituisce:
    - ``gdf_segmenti``: GeoDataFrame dei segmenti con geometria
      ``MultiLineString`` (semplice unione delle geometrie degli archi
      del segmento).
    - ``df_arco_segmento``: mapping ``id_arco -> id_segmento``.
    """
    log.info(
        "Segmentazione: %d archi, soglia_var_tgm=%.2f, lung_min=%.0f, lung_max=%.0f",
        len(gdf_rete),
        soglia_var_tgm,
        lung_min,
        lung_max,
    )
    indice = _costruisci_indice_archi(gdf_rete, df_archi_nodi, df_nodi)
    catene = _costruisci_catene(
        indice, soglia_var_tgm=soglia_var_tgm,
        id_nodi_intersezione=id_nodi_intersezione,
    )
    log.info("Catene massimali costruite: %d", len(catene))
    segmenti = _spezza_per_lunghezza(catene, indice["arco_lung"], lung_max=lung_max)
    log.info("Segmenti dopo split per lunghezza max: %d", len(segmenti))

    # Indici di lookup per attributi degli archi.
    rete_idx = gdf_rete.set_index("id_arco")

    arco_endpoints = indice["arco_endpoints"]
    nodo_grado = indice["nodo_grado"]

    record_seg: list[dict[str, Any]] = []
    geometrie: list[Any] = []
    record_map: list[tuple[int, int]] = []

    for id_segmento, catena in enumerate(segmenti):
        sub = rete_idx.loc[catena]
        lunghezza_tot = float(sub["lunghezza_m"].fillna(0).sum())
        pesi = sub["lunghezza_m"].fillna(0).to_numpy(dtype=float)
        tgm_medio = _media_pesata(sub["tgm"].to_numpy(dtype=float), pesi)
        v85_medio = (
            _media_pesata(sub["v_85"].to_numpy(dtype=float), pesi)
            if "v_85" in sub.columns
            else float("nan")
        )
        limite_medio = (
            _media_pesata(sub["limite_velocita"].to_numpy(dtype=float), pesi)
            if "limite_velocita" in sub.columns
            else float("nan")
        )
        eccesso_medio = (
            _media_pesata(sub["eccesso_v85"].to_numpy(dtype=float), pesi)
            if "eccesso_v85" in sub.columns
            else float("nan")
        )
        iqr_medio = (
            _media_pesata(sub["iqr_norm"].to_numpy(dtype=float), pesi)
            if "iqr_norm" in sub.columns
            else float("nan")
        )
        # Dispersione velocita' pura (V75-V25 in km/h), indipendente dal
        # limite di velocita' (i limiti non sono sempre aggiornati).
        iqr_kmh_medio = (
            _media_pesata(sub["iqr_velocita"].to_numpy(dtype=float), pesi)
            if "iqr_velocita" in sub.columns
            else float("nan")
        )

        toponimo_visualizzato = _moda_categoriale(sub["toponimo"]) if "toponimo" in sub.columns else None
        classe_frc = _moda_categoriale(sub["classe_frc"]) if "classe_frc" in sub.columns else None
        pgtu_classifica = (
            _moda_categoriale(sub["pgtu_classifica"]) if "pgtu_classifica" in sub.columns else None
        )
        pgtu_tpl = (
            bool(sub["pgtu_tpl"].fillna(0).astype(bool).any())
            if "pgtu_tpl" in sub.columns
            else False
        )
        grande_viab = (
            bool(sub["grande_viabilita"].fillna(0).astype(bool).any())
            if "grande_viabilita" in sub.columns
            else False
        )
        linea_atac = (
            bool(sub["linea_atac"].fillna(False).astype(bool).any())
            if "linea_atac" in sub.columns
            else False
        )
        extraurbana_cdr = (
            bool(sub["is_extraurbana_cdr"].fillna(False).astype(bool).any())
            if "is_extraurbana_cdr" in sub.columns
            else False
        )
        extraurbana_altri_enti = (
            bool(sub["is_extraurbana_altri_enti"].fillna(False).astype(bool).any())
            if "is_extraurbana_altri_enti" in sub.columns
            else False
        )

        nodo_start, nodo_end = _estremi_catena(catena, arco_endpoints)
        grado_start = int(nodo_grado.get(nodo_start, 0))
        grado_end = int(nodo_grado.get(nodo_end, 0))

        # Geometria: unione delle geometrie degli archi del segmento.
        geom_seg = sub.geometry.union_all()
        geometrie.append(geom_seg)

        record_seg.append(
            {
                "id_segmento": id_segmento,
                "toponimo": toponimo_visualizzato,
                "n_archi": int(len(catena)),
                "lunghezza_m": lunghezza_tot,
                "tgm_medio": tgm_medio,
                "v85_medio": v85_medio,
                "limite_velocita_medio": limite_medio,
                "eccesso_v85_medio": eccesso_medio,
                "iqr_norm_medio": iqr_medio,
                "iqr_velocita_medio": iqr_kmh_medio,
                "classe_frc": classe_frc,
                "pgtu_classifica": pgtu_classifica,
                "pgtu_tpl": pgtu_tpl,
                "grande_viabilita": grande_viab,
                "linea_atac": linea_atac,
                "is_extraurbana_cdr": extraurbana_cdr,
                "is_extraurbana_altri_enti": extraurbana_altri_enti,
                "id_nodo_start": int(nodo_start),
                "id_nodo_end": int(nodo_end),
                "grado_start": grado_start,
                "grado_end": grado_end,
                "isolato": bool(lunghezza_tot < lung_min),
                "archi": [int(a) for a in catena],
            }
        )

        for ida in catena:
            record_map.append((int(ida), id_segmento))

    gdf_segmenti = gpd.GeoDataFrame(
        record_seg, geometry=geometrie, crs=gdf_rete.crs
    )
    df_arco_segmento = pd.DataFrame.from_records(
        record_map, columns=["id_arco", "id_segmento"]
    )
    log.info(
        "Segmenti finali: %d (di cui %d isolati < %.0f m)",
        len(gdf_segmenti),
        int(gdf_segmenti["isolato"].sum()),
        lung_min,
    )
    return gdf_segmenti, df_arco_segmento


def riassumi_segmenti(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Riassunto descrittivo del dataset dei segmenti."""
    if len(gdf) == 0:
        return {"n_segmenti": 0}
    lunghezze = gdf["lunghezza_m"].astype(float)
    return {
        "n_segmenti": int(len(gdf)),
        "n_isolati": int(gdf["isolato"].sum()) if "isolato" in gdf.columns else 0,
        "lunghezza_totale_km": float(lunghezze.sum() / 1000.0),
        "lunghezza_mediana_m": float(lunghezze.median()),
        "lunghezza_p10_m": float(lunghezze.quantile(0.10)),
        "lunghezza_p90_m": float(lunghezze.quantile(0.90)),
        "lunghezza_max_m": float(lunghezze.max()),
        "n_archi_per_segmento_mediana": float(gdf["n_archi"].median()),
    }


def salva_segmenti(gdf: gpd.GeoDataFrame, percorso: Path) -> None:
    """Salva il GeoDataFrame dei segmenti in GeoPackage.

    La colonna ``archi`` (lista di int) viene serializzata come stringa
    ``|``-separata, analogamente alle intersezioni.
    """
    percorso.parent.mkdir(parents=True, exist_ok=True)
    if percorso.exists():
        percorso.unlink()

    gdf_out = gdf.copy()
    if "archi" in gdf_out.columns:
        gdf_out["archi"] = gdf_out["archi"].apply(
            lambda lst: "|".join(str(x) for x in lst) if isinstance(lst, list) else ""
        )

    log.info("Salvataggio segmenti: %s (%d record)", percorso, len(gdf_out))
    gdf_out.to_file(percorso, driver="GPKG", layer="segmenti")


# ---------------------------------------------------------------------------
# Matching incidenti -> intersezioni/segmenti (Task 1.2 + 1.3)
# ---------------------------------------------------------------------------


def _nome_strada_incidente(valore: Any) -> str | None:
    """Normalizza il toponimo di un incidente per il matching fuzzy.

    Applica la stessa normalizzazione dei segmenti (``_norm_topo``),
    cosi' i punteggi rapidfuzz sono confrontabili.
    """
    return _norm_topo(valore)


def abbinamento_geometrico_intersezioni(
    gdf_incidenti: gpd.GeoDataFrame,
    gdf_intersezioni: gpd.GeoDataFrame,
    raggio_m: float,
) -> pd.DataFrame:
    """Per ogni incidente trova l'intersezione piu' vicina.

    Restituisce un DataFrame indicizzato su ``id_incidente`` con colonne
    ``id_nodo_vicino``, ``distanza_int_m``, ``match_intersezione`` (bool
    ``True`` se ``distanza_int_m <= raggio_m``).
    """
    if gdf_incidenti.crs != gdf_intersezioni.crs:
        gdf_incidenti = gdf_incidenti.to_crs(gdf_intersezioni.crs)

    joined = gpd.sjoin_nearest(
        gdf_incidenti[["id_incidente", "geometry"]],
        gdf_intersezioni[["id_nodo", "geometry"]],
        how="left",
        distance_col="distanza_int_m",
    )
    # sjoin_nearest puo' restituire piu' righe per incidente se ci sono ties:
    # teniamo la prima.
    joined = joined.drop_duplicates(subset=["id_incidente"], keep="first")
    joined = joined.rename(columns={"id_nodo": "id_nodo_vicino"})
    joined["match_intersezione"] = joined["distanza_int_m"] <= raggio_m
    return joined.set_index("id_incidente")[
        ["id_nodo_vicino", "distanza_int_m", "match_intersezione"]
    ]


def abbinamento_geometrico_segmenti(
    gdf_incidenti: gpd.GeoDataFrame,
    gdf_segmenti: gpd.GeoDataFrame,
    soglia_m: float,
) -> pd.DataFrame:
    """Per ogni incidente trova il segmento geometricamente piu' vicino.

    Restituisce un DataFrame indicizzato su ``id_incidente`` con colonne
    ``id_segmento_vicino``, ``distanza_seg_m``, ``match_segmento`` (bool
    ``True`` se ``distanza_seg_m <= soglia_m``).
    """
    if gdf_incidenti.crs != gdf_segmenti.crs:
        gdf_incidenti = gdf_incidenti.to_crs(gdf_segmenti.crs)

    joined = gpd.sjoin_nearest(
        gdf_incidenti[["id_incidente", "geometry"]],
        gdf_segmenti[["id_segmento", "geometry"]],
        how="left",
        distance_col="distanza_seg_m",
    )
    joined = joined.drop_duplicates(subset=["id_incidente"], keep="first")
    joined = joined.rename(columns={"id_segmento": "id_segmento_vicino"})
    joined["match_segmento"] = joined["distanza_seg_m"] <= soglia_m
    return joined.set_index("id_incidente")[
        ["id_segmento_vicino", "distanza_seg_m", "match_segmento"]
    ]


def abbinamento_toponomastico(
    gdf_incidenti_residui: gpd.GeoDataFrame,
    gdf_segmenti: gpd.GeoDataFrame,
    raggio_m: float,
    soglia_fuzzy: int = 85,
) -> pd.DataFrame:
    """Fallback toponomastico: trova il segmento compatibile per nome.

    Per ogni incidente residuo cerca i segmenti entro ``raggio_m`` metri
    e, fra quelli con toponimo gia' normalizzato compatibile
    (``rapidfuzz.fuzz.token_set_ratio >= soglia_fuzzy``), sceglie quello
    geometricamente piu' vicino.

    Restituisce un DataFrame indicizzato su ``id_incidente`` con colonne
    ``id_segmento_topon``, ``distanza_topon_m``, ``score_topon`` (int).
    Incidenti senza candidato valido NON vengono inclusi nel risultato.
    """
    from rapidfuzz import fuzz

    if len(gdf_incidenti_residui) == 0 or len(gdf_segmenti) == 0:
        return pd.DataFrame(
            columns=["id_segmento_topon", "distanza_topon_m", "score_topon"]
        )

    if gdf_incidenti_residui.crs != gdf_segmenti.crs:
        gdf_incidenti_residui = gdf_incidenti_residui.to_crs(gdf_segmenti.crs)

    # Normalizza i toponimi per il fuzzy match.
    inc = gdf_incidenti_residui.copy()
    inc["_topo_norm"] = inc["strada1"].apply(_nome_strada_incidente)
    # Scarta gli incidenti senza nome strada: impossibile fallback.
    inc = inc.loc[inc["_topo_norm"].notna()]
    if len(inc) == 0:
        return pd.DataFrame(
            columns=["id_segmento_topon", "distanza_topon_m", "score_topon"]
        )

    seg = gdf_segmenti[["id_segmento", "toponimo", "geometry"]].copy()
    seg["_topo_norm"] = seg["toponimo"].apply(_norm_topo)

    # Join spaziale "dwithin" con buffer: per ogni incidente tutti i
    # segmenti entro raggio_m. Implementato via sjoin su buffer circolare
    # per compatibilita' con versioni vecchie di geopandas.
    inc_buf = inc[["id_incidente", "_topo_norm", "geometry"]].copy()
    inc_buf["geometry"] = inc_buf.geometry.buffer(raggio_m)

    joined = gpd.sjoin(
        inc_buf,
        seg[["id_segmento", "_topo_norm", "geometry"]].rename(
            columns={"_topo_norm": "_topo_norm_seg"}
        ),
        how="inner",
        predicate="intersects",
    )
    if len(joined) == 0:
        return pd.DataFrame(
            columns=["id_segmento_topon", "distanza_topon_m", "score_topon"]
        )

    # Calcola il punteggio fuzzy riga per riga.
    scores = np.array(
        [
            fuzz.token_set_ratio(a or "", b or "")
            for a, b in zip(joined["_topo_norm"].values, joined["_topo_norm_seg"].values)
        ],
        dtype=float,
    )
    joined["score_topon"] = scores
    joined = joined.loc[joined["score_topon"] >= soglia_fuzzy].copy()
    if len(joined) == 0:
        return pd.DataFrame(
            columns=["id_segmento_topon", "distanza_topon_m", "score_topon"]
        )

    # Calcola la distanza geometrica reale incidente <-> segmento
    # per fare il tie-break (prendi il piu' vicino a parita' di score).
    inc_pts = inc[["id_incidente", "geometry"]].set_index("id_incidente")
    seg_geom = seg[["id_segmento", "geometry"]].set_index("id_segmento")

    idx_inc = joined["id_incidente"].to_numpy()
    idx_seg = joined["id_segmento"].to_numpy()
    pts_a = inc_pts.loc[idx_inc, "geometry"].values
    pts_b = seg_geom.loc[idx_seg, "geometry"].values
    distanze = np.array(
        [a.distance(b) for a, b in zip(pts_a, pts_b)], dtype=float
    )
    joined["distanza_topon_m"] = distanze

    # Per ogni incidente, scegli prima per score discendente, poi per
    # distanza crescente.
    joined = joined.sort_values(
        by=["id_incidente", "score_topon", "distanza_topon_m"],
        ascending=[True, False, True],
    )
    best = joined.drop_duplicates(subset=["id_incidente"], keep="first")
    best = best.rename(columns={"id_segmento": "id_segmento_topon"})
    return best.set_index("id_incidente")[
        ["id_segmento_topon", "distanza_topon_m", "score_topon"]
    ]


def abbina_incidenti(
    gdf_incidenti: gpd.GeoDataFrame,
    gdf_intersezioni: gpd.GeoDataFrame,
    gdf_segmenti: gpd.GeoDataFrame,
    raggio_intersezione_m: float,
    soglia_snap_geometrica_m: float,
    soglia_snap_toponomastica_m: float,
    soglia_fuzzy: int = 85,
) -> gpd.GeoDataFrame:
    """Abbinamento incidenti -> rete, secondo la gerarchia del Task 1.2/1.3.

    Regole (nell'ordine):

    1. Se l'incidente cade entro ``raggio_intersezione_m`` da un nodo
       intersezione, viene abbinato all'intersezione
       (``match_type="intersezione"``).
    2. Altrimenti, se cade entro ``soglia_snap_geometrica_m`` da un
       segmento, viene abbinato al segmento piu' vicino
       (``match_type="segmento"``).
    3. Altrimenti si tenta il fallback toponomastico entro
       ``soglia_snap_toponomastica_m``: fra i segmenti nel raggio, si
       sceglie quello col miglior match fuzzy sul nome strada
       (``match_type="segmento_toponimo"``).
    4. Altrimenti l'incidente resta ``match_type="non_abbinato"``.

    Restituisce il GeoDataFrame degli incidenti con le nuove colonne:
    ``match_type``, ``id_match`` (id_nodo o id_segmento), ``distanza_match_m``,
    ``score_topon`` (NaN se non toponomastico).
    """
    log.info(
        "Abbinamento incidenti: %d incidenti, %d intersezioni, %d segmenti",
        len(gdf_incidenti),
        len(gdf_intersezioni),
        len(gdf_segmenti),
    )

    # 1. Nearest intersezione per ogni incidente.
    log.info("  step 1: nearest intersezione (raggio %.0f m)", raggio_intersezione_m)
    df_int = abbinamento_geometrico_intersezioni(
        gdf_incidenti, gdf_intersezioni, raggio_m=raggio_intersezione_m
    )

    # 2. Nearest segmento per ogni incidente.
    log.info("  step 2: nearest segmento (soglia %.0f m)", soglia_snap_geometrica_m)
    df_seg = abbinamento_geometrico_segmenti(
        gdf_incidenti, gdf_segmenti, soglia_m=soglia_snap_geometrica_m
    )

    # Prepara il risultato di default (non abbinato).
    out = gdf_incidenti.copy()
    out = out.merge(df_int, left_on="id_incidente", right_index=True, how="left")
    out = out.merge(df_seg, left_on="id_incidente", right_index=True, how="left")

    out["match_type"] = "non_abbinato"
    out["id_match"] = pd.Series([pd.NA] * len(out), dtype="Int64")
    out["distanza_match_m"] = np.nan

    # Priorita' 1: intersezione.
    mask_int = out["match_intersezione"].fillna(False)
    out.loc[mask_int, "match_type"] = "intersezione"
    out.loc[mask_int, "id_match"] = out.loc[mask_int, "id_nodo_vicino"].astype("Int64")
    out.loc[mask_int, "distanza_match_m"] = out.loc[mask_int, "distanza_int_m"]

    # Priorita' 2: segmento geometrico (solo su chi non e' gia' intersezione).
    mask_seg = ~mask_int & out["match_segmento"].fillna(False)
    out.loc[mask_seg, "match_type"] = "segmento"
    out.loc[mask_seg, "id_match"] = out.loc[mask_seg, "id_segmento_vicino"].astype("Int64")
    out.loc[mask_seg, "distanza_match_m"] = out.loc[mask_seg, "distanza_seg_m"]

    # Priorita' 3: fallback toponomastico.
    residui_mask = ~mask_int & ~mask_seg
    n_residui = int(residui_mask.sum())
    log.info("  step 3: fallback toponomastico su %d residui", n_residui)

    out["score_topon"] = np.nan
    if n_residui > 0:
        gdf_residui = out.loc[residui_mask, ["id_incidente", "strada1", "geometry"]].copy()
        df_topon = abbinamento_toponomastico(
            gdf_residui,
            gdf_segmenti,
            raggio_m=soglia_snap_toponomastica_m,
            soglia_fuzzy=soglia_fuzzy,
        )
        if len(df_topon) > 0:
            # Propaga i risultati toponomastici tramite un lookup puntuale.
            topon_map = df_topon.to_dict(orient="index")
            ids_topon = out.loc[residui_mask, "id_incidente"].to_numpy()
            for pos, id_inc in zip(out.index[residui_mask], ids_topon):
                rec = topon_map.get(id_inc)
                if rec is None:
                    continue
                out.at[pos, "match_type"] = "segmento_toponimo"
                out.at[pos, "id_match"] = int(rec["id_segmento_topon"])
                out.at[pos, "distanza_match_m"] = float(rec["distanza_topon_m"])
                out.at[pos, "score_topon"] = float(rec["score_topon"])

    # Pulizia colonne intermedie.
    out = out.drop(
        columns=[
            "id_nodo_vicino",
            "distanza_int_m",
            "match_intersezione",
            "id_segmento_vicino",
            "distanza_seg_m",
            "match_segmento",
        ],
        errors="ignore",
    )

    # Log riassuntivo.
    conteggi = out["match_type"].value_counts().to_dict()
    log.info("  Esito matching: %s", conteggi)

    # Verifica: nessun doppio conteggio.
    n_tot = sum(conteggi.values())
    assert n_tot == len(gdf_incidenti), (
        f"Doppio conteggio nel matching: {n_tot} assegnazioni vs "
        f"{len(gdf_incidenti)} incidenti"
    )

    return out


def riassumi_matching(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Riassunto del risultato di ``abbina_incidenti``."""
    if len(gdf) == 0:
        return {"n_incidenti": 0}
    r: dict[str, Any] = {"n_incidenti": int(len(gdf))}
    counts = gdf["match_type"].value_counts().to_dict()
    for k in ("intersezione", "segmento", "segmento_toponimo", "non_abbinato"):
        r[f"n_{k}"] = int(counts.get(k, 0))
    abbinati = gdf.loc[gdf["match_type"] != "non_abbinato"]
    if len(abbinati) > 0:
        r["distanza_match_mediana_m"] = float(abbinati["distanza_match_m"].median())
        r["distanza_match_p90_m"] = float(abbinati["distanza_match_m"].quantile(0.90))
    return r


def salva_incidenti_matched(gdf: gpd.GeoDataFrame, percorso: Path) -> None:
    """Salva il GeoDataFrame degli incidenti con matching su GeoPackage."""
    percorso.parent.mkdir(parents=True, exist_ok=True)
    if percorso.exists():
        percorso.unlink()
    log.info("Salvataggio incidenti_matched: %s (%d record)", percorso, len(gdf))
    gdf.to_file(percorso, driver="GPKG", layer="incidenti_matched")


# ---------------------------------------------------------------------------
# Pipeline principale
# ---------------------------------------------------------------------------


def main(config: dict[str, Any]) -> None:
    """Entry point dello step.

    Al momento esegue solo Task 1.1a (estrazione intersezioni e associazione
    semafori). I passi successivi (segmentazione e matching incidenti)
    verranno aggiunti nei commit successivi.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Caricamento rete preparata.
    rete_rel = config["paths"]["interim"]["rete_tomtom_prep"]
    rete_path = RADICE_PROGETTO / rete_rel
    log.info("Caricamento rete preparata da %s", rete_path)
    gdf_rete = gpd.read_file(rete_path, layer="rete_prep")
    log.info("Caricati %d archi con CRS %s", len(gdf_rete), gdf_rete.crs)

    # Caricamento semafori preparati.
    sem_rel = config["paths"]["interim"]["semafori_prep"]
    sem_path = RADICE_PROGETTO / sem_rel
    log.info("Caricamento semafori preparati da %s", sem_path)
    gdf_semafori = gpd.read_file(sem_path, layer="semafori_prep")
    log.info("Caricati %d semafori con CRS %s", len(gdf_semafori), gdf_semafori.crs)

    # Estrazione intersezioni.
    tolleranza_nodo = float(
        config.get("matching", {}).get("tolleranza_nodo", 0.5)
    )
    filtra_incroci = config.get("matching", {}).get("filtra_falsi_incroci", True)
    raggio_cluster_int = float(
        config.get("matching", {}).get("raggio_cluster_intersezioni", 30.0)
    )
    raggio_topo_int = float(
        config.get("matching", {}).get("raggio_toponimi_intersezione", 20.0)
    )
    gdf_intersezioni, df_archi_nodi = estrai_intersezioni(
        gdf_rete,
        tolleranza_m=tolleranza_nodo,
        filtra_falsi_incroci=filtra_incroci,
        raggio_cluster_intersezioni_m=raggio_cluster_int,
        raggio_toponimi_m=raggio_topo_int,
    )

    # Per la segmentazione servono anche tutti i nodi (non solo le
    # intersezioni). Le ricalcoliamo dal df_endpoint usando la stessa
    # tolleranza: e' un calcolo veloce e mantiene il modulo
    # ``costruisci_segmenti`` indipendente dalla forma di ``gdf_intersezioni``.
    df_ep = estrai_endpoint_archi(gdf_rete)
    df_nodi_tutti, _ = costruisci_nodi(df_ep, tolleranza_m=tolleranza_nodo)

    # Associazione semafori.
    raggio_sem = float(config["matching"]["raggio_associazione_semaforo"])
    raggio_sem_max = config["matching"].get(
        "raggio_max_associazione_semaforo", 100.0
    )
    gdf_intersezioni = associa_semafori(
        gdf_intersezioni, gdf_semafori, raggio_m=raggio_sem,
        raggio_max_m=(float(raggio_sem_max) if raggio_sem_max is not None
                      else None),
    )

    # Riassunto intersezioni.
    riassunto = riassumi_intersezioni(gdf_intersezioni)
    log.info("Riassunto intersezioni:")
    for chiave, valore in riassunto.items():
        log.info("  %s: %s", chiave, valore)

    # Salvataggio intersezioni.
    out_int_rel = config["paths"]["interim"]["intersezioni"]
    out_int_path = RADICE_PROGETTO / out_int_rel
    salva_intersezioni(gdf_intersezioni, out_int_path)

    # Segmentazione omogenea (Task 1.1b).
    soglia_var_tgm = float(config["matching"]["soglia_variazione_tgm_segmento"])
    lung_min = float(config["matching"]["lunghezza_min_segmento"])
    lung_max = float(config["matching"]["lunghezza_max_segmento"])
    id_nodi_int = set(gdf_intersezioni["id_nodo"].tolist())
    gdf_segmenti, _df_arco_segmento = costruisci_segmenti(
        gdf_rete,
        df_archi_nodi=df_archi_nodi,
        df_nodi=df_nodi_tutti,
        soglia_var_tgm=soglia_var_tgm,
        lung_min=lung_min,
        lung_max=lung_max,
        id_nodi_intersezione=id_nodi_int,
    )

    # Riassunto segmenti.
    riassunto_seg = riassumi_segmenti(gdf_segmenti)
    log.info("Riassunto segmenti:")
    for chiave, valore in riassunto_seg.items():
        log.info("  %s: %s", chiave, valore)

    # Salvataggio segmenti.
    out_seg_rel = config["paths"]["interim"]["segmenti"]
    out_seg_path = RADICE_PROGETTO / out_seg_rel
    salva_segmenti(gdf_segmenti, out_seg_path)

    # Matching incidenti (Task 1.2 + 1.3).
    inc_rel = config["paths"]["interim"]["incidenti_clean"]
    inc_path = RADICE_PROGETTO / inc_rel
    log.info("Caricamento incidenti puliti da %s", inc_path)
    gdf_incidenti = gpd.read_file(inc_path)
    log.info("Caricati %d incidenti con CRS %s", len(gdf_incidenti), gdf_incidenti.crs)

    raggio_int = float(config["matching"]["raggio_intersezione"])
    soglia_geo = float(config["matching"]["soglia_snap_geometrica"])
    soglia_topon = float(config["matching"]["soglia_snap_toponomastica"])
    gdf_matched = abbina_incidenti(
        gdf_incidenti,
        gdf_intersezioni,
        gdf_segmenti,
        raggio_intersezione_m=raggio_int,
        soglia_snap_geometrica_m=soglia_geo,
        soglia_snap_toponomastica_m=soglia_topon,
    )

    riassunto_match = riassumi_matching(gdf_matched)
    log.info("Riassunto matching:")
    for chiave, valore in riassunto_match.items():
        log.info("  %s: %s", chiave, valore)

    out_match_rel = config["paths"]["interim"]["incidenti_matched"]
    out_match_path = RADICE_PROGETTO / out_match_rel
    salva_incidenti_matched(gdf_matched, out_match_path)


if __name__ == "__main__":
    main(carica_config())
