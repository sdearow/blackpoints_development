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


def estrai_intersezioni(
    gdf_rete: gpd.GeoDataFrame,
    tolleranza_m: float = 0.5,
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

    return gdf_intersezioni, df_archi_nodi


# ---------------------------------------------------------------------------
# Associazione semafori -> intersezioni
# ---------------------------------------------------------------------------


def associa_semafori(
    gdf_intersezioni: gpd.GeoDataFrame,
    gdf_semafori: gpd.GeoDataFrame,
    raggio_m: float,
) -> gpd.GeoDataFrame:
    """Associa ogni semaforo veicolare al nodo-intersezione piu' vicino.

    Strategia (scelta dall'utente, opzione C del setup):
    - ogni semaforo ``is_veicolare`` viene associato in modo assoluto al
      nodo piu' vicino, indipendentemente dalla distanza;
    - se la distanza supera ``raggio_m``, l'associazione viene loggata
      come warning (ma il nodo risulta comunque semaforizzato);
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

    # sjoin_nearest: per ogni semaforo trova l'intersezione piu' vicina
    # (nessun limite di distanza: scelta C dell'utente).
    joined = gpd.sjoin_nearest(
        gdf_v[["id_impianto", "geometry"]],
        gdf_intersezioni[["id_nodo", "geometry"]],
        how="left",
        distance_col="distanza_m",
    )

    # Log di warning per i semafori oltre soglia.
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
    for col in ("archi", "toponimi", "id_impianti"):
        if col in gdf_out.columns:
            gdf_out[col] = gdf_out[col].apply(
                lambda lst: "|".join(str(x) for x in lst) if isinstance(lst, list) else ""
            )

    log.info("Salvataggio intersezioni: %s (%d record)", percorso, len(gdf_out))
    gdf_out.to_file(percorso, driver="GPKG", layer="intersezioni")


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
    gdf_intersezioni, _df_archi_nodi = estrai_intersezioni(
        gdf_rete, tolleranza_m=tolleranza_nodo
    )

    # Associazione semafori.
    raggio_sem = float(config["matching"]["raggio_associazione_semaforo"])
    gdf_intersezioni = associa_semafori(
        gdf_intersezioni, gdf_semafori, raggio_m=raggio_sem
    )

    # Riassunto.
    riassunto = riassumi_intersezioni(gdf_intersezioni)
    log.info("Riassunto intersezioni:")
    for chiave, valore in riassunto.items():
        log.info("  %s: %s", chiave, valore)

    # Salvataggio.
    out_rel = config["paths"]["interim"]["intersezioni"]
    out_path = RADICE_PROGETTO / out_rel
    salva_intersezioni(gdf_intersezioni, out_path)


if __name__ == "__main__":
    main(carica_config())
