"""Step 01 - Preparazione della rete TomTom + join PGTU 2026 (Fase 0, Task 0.2).

Carica il GeoPackage della rete TomTom ``rete_tomtom.gpkg``, valida la
topologia di base, rinomina le colonne in snake_case italiano parlante,
normalizza i flag testuali (``Si``/``No``), calcola le derivate di flusso e
velocita' che alimenteranno gli SPF (``log_tgm``, ``log_lunghezza``,
``iqr_norm``, ``ratio_v85_limite``) e riproietta gli archi nel CRS metrico
di lavoro. Infine aggancia spazialmente la classificazione funzionale del
grafo PGTU 2026 (classifica, grande viabilita', trasporto pubblico locale).

Osservazioni sul file sorgente (layer ``tomtom_data_2024``):
- CRS nativo: ``EPSG:3004`` (Gauss-Boaga Italia zona 2), lo stesso degli
  incidenti. Tutto il calcolo geometrico resta in questo sistema finche' non
  riproiettiamo a ``EPSG:32633`` per l'output.
- Geometria: ``MultiLineString Z``.
- ``StreetName``: toponimo gia' normalizzato, senza nulli (6.885 uniche
  osservate su 94.148 archi), quindi utilizzabile direttamente per il
  matching toponomastico nelle fasi successive.
- ``VEIC_DAY_T``: veicoli/giorno totali = TGM.
- ``BS_P*sp``: percentili della velocita' istantanea rilevata; ``BS_P85sp``
  e' la V85 usata come proxy di "velocita' operativa" nel criterio di
  rischio velocita'.
- ``SpeedLimit``: limite di velocita' vigente (km/h).
- ``Shape_Leng``: lunghezza arco in metri (calcolata sul CRS metrico
  nativo EPSG:3004).

Le colonne ``GV2019`` e ``CF_PGTU201`` presenti nel file TomTom vengono
ignorate (sono datate al 2019): la classifica funzionale e il flag grande
viabilita' derivano dal grafo PGTU 2026 fornito dal Comune di Roma tramite
join spaziale per midpoint dell'arco.

Grafo PGTU 2026:
- File: ``data/raw/2a.PGTU_Grafo_2026.geojson``, CRS EPSG:4326, 1.309 archi.
- Campi significativi: ``classifica`` (S/IQ/IZ/Q), ``grande_viabilita``
  (Si/No), ``tpl`` (Si/No).
- Match: per ogni arco TomTom si prende il midpoint geometrico e si trova
  l'arco PGTU piu' vicino entro ``matching.raggio_associazione_pgtu`` metri.
  Gli archi TomTom oltre la soglia restano senza classificazione PGTU
  (corrispondono tipicamente a strade locali fuori dal grafo PGTU).

Output atteso: ``data/interim/rete_tomtom_prep.gpkg`` (layer ``rete_prep``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from src.config import RADICE_PROGETTO, carica_config

log = logging.getLogger("s01_preparazione_rete")


# ---------------------------------------------------------------------------
# Mappatura colonne TomTom -> nomi puliti del progetto
# ---------------------------------------------------------------------------

#: Colonne del file TomTom che vengono esplicitamente ignorate e droppate
#: dal dataframe in ``standardizza_colonne``. ``GV2019`` e ``CF_PGTU201``
#: contengono la classificazione funzionale al 2019, ma per il progetto
#: usiamo il grafo PGTU 2026 joinato spazialmente piu' avanti.
COLONNE_DA_IGNORARE: tuple[str, ...] = ("GV2019", "CF_PGTU201")

MAPPATURA_COLONNE: dict[str, str] = {
    "Id": "id_arco",
    "FRC": "classe_frc",
    "SpeedLimit": "limite_velocita",
    "StreetName": "toponimo",
    "VEIC_DAY_T": "tgm",
    "VEIC_0809_": "flusso_0809",
    "VEIC_1819_": "flusso_1819",
    "VEIC_08091": "flusso_punta",
    "PCT_PUNTA_": "pct_punta",
    "ATAC": "linea_atac",
    "BS_AvgTt": "tempo_medio",
    "BS_MedTt": "tempo_mediano",
    "BS_ratio": "ratio_congestione",
    "BS_AvgSp": "v_media",
    "BS_HvgSp": "v_armonica",
    "BS_MedSp": "v_mediana",
    "BS_SdSp": "v_std",
    "BS_P5sp": "v_p05",
    "BS_P10sp": "v_p10",
    "BS_P15sp": "v_p15",
    "BS_P20sp": "v_p20",
    "BS_P25sp": "v_p25",
    "BS_P30sp": "v_p30",
    "BS_P35sp": "v_p35",
    "BS_P40sp": "v_p40",
    "BS_P45sp": "v_p45",
    "BS_P50sp": "v_p50",
    "BS_P55sp": "v_p55",
    "BS_P60sp": "v_p60",
    "BS_P65sp": "v_p65",
    "BS_P70sp": "v_p70",
    "BS_P75sp": "v_p75",
    "BS_P80sp": "v_p80",
    "BS_P85sp": "v_85",
    "BS_P90sp": "v_p90",
    "BS_P95sp": "v_p95",
    "Shape_Leng": "lunghezza_m",
}


# ---------------------------------------------------------------------------
# Caricamento
# ---------------------------------------------------------------------------


def carica_rete_tomtom(
    percorso: Path,
    layer: str = "tomtom_data_2024",
) -> gpd.GeoDataFrame:
    """Carica il GeoPackage TomTom e restituisce un GeoDataFrame."""
    if not percorso.exists():
        raise FileNotFoundError(f"File rete TomTom non trovato: {percorso}")
    log.info("Caricamento rete TomTom da %s (layer=%s)", percorso, layer)
    gdf = gpd.read_file(percorso, layer=layer)
    log.info("Caricati %d archi con CRS %s", len(gdf), gdf.crs)
    return gdf


# ---------------------------------------------------------------------------
# Validazione topologica
# ---------------------------------------------------------------------------


def valida_rete(gdf: gpd.GeoDataFrame) -> dict[str, int]:
    """Esegue controlli di sanita' sulla rete e logga le anomalie.

    Ritorna un dizionario con i conteggi delle anomalie. Non modifica il
    GeoDataFrame: le correzioni vengono applicate da funzioni dedicate.
    """
    diagnosi = {
        "n_totali": int(len(gdf)),
        "n_geom_nulle": int(gdf.geometry.isna().sum()),
        "n_geom_vuote": int(gdf.geometry.is_empty.sum()),
        "n_geom_invalide": int((~gdf.geometry.is_valid).sum()),
        "n_duplicati_id": 0,
    }

    if "Id" in gdf.columns:
        diagnosi["n_duplicati_id"] = int(gdf["Id"].duplicated().sum())

    for chiave, valore in diagnosi.items():
        if chiave == "n_totali":
            log.info("Validazione rete: %d archi totali", valore)
        elif valore > 0:
            log.warning("Validazione rete: %s = %d", chiave, valore)

    return diagnosi


# ---------------------------------------------------------------------------
# Standardizzazione colonne e flag
# ---------------------------------------------------------------------------


def _boolifica_si_no(serie: pd.Series) -> pd.Series:
    """Converte una serie con valori 'Si'/'No' (case-insensitive) in boolean."""
    normalizzata = serie.astype(str).str.strip().str.lower()
    mappa = {"si": True, "sì": True, "s": True, "yes": True, "y": True, "true": True, "1": True,
             "no": False, "n": False, "false": False, "0": False}
    return normalizzata.map(mappa).astype("boolean")


def _pulisci_categoria(serie: pd.Series) -> pd.Series:
    """Converte stringhe vuote/``-``/``nan`` di una colonna categoriale in NaN."""
    valori = serie.astype(str).str.strip().replace({"-": None, "": None, "nan": None, "None": None})
    return valori.astype("category")


def standardizza_colonne(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Rinomina le colonne TomTom, normalizza i tipi e droppa i campi inutili."""
    # Droppa i campi ignorati (GV2019, CF_PGTU201 - datati 2019).
    da_droppare = [c for c in COLONNE_DA_IGNORARE if c in gdf.columns]
    if da_droppare:
        gdf = gdf.drop(columns=da_droppare)

    gdf = gdf.rename(columns={k: v for k, v in MAPPATURA_COLONNE.items() if k in gdf.columns})

    # Cast numerici (sono gia' float64 ma forziamo per sicurezza).
    colonne_numeriche = [
        "id_arco", "classe_frc", "limite_velocita", "tgm",
        "flusso_0809", "flusso_1819", "flusso_punta", "pct_punta",
        "tempo_medio", "tempo_mediano", "ratio_congestione",
        "v_media", "v_armonica", "v_mediana", "v_std",
        "v_p05", "v_p10", "v_p15", "v_p20", "v_p25", "v_p30", "v_p35",
        "v_p40", "v_p45", "v_p50", "v_p55", "v_p60", "v_p65", "v_p70",
        "v_p75", "v_p80", "v_85", "v_p90", "v_p95",
        "lunghezza_m",
    ]
    for col in colonne_numeriche:
        if col in gdf.columns:
            gdf[col] = pd.to_numeric(gdf[col], errors="coerce")

    # id_arco come intero nullable (per chiarezza negli output).
    if "id_arco" in gdf.columns:
        gdf["id_arco"] = gdf["id_arco"].astype("Int64")

    # classe_frc come intero nullable (0-7, scala TomTom).
    if "classe_frc" in gdf.columns:
        gdf["classe_frc"] = gdf["classe_frc"].astype("Int64")

    # Flag ATAC: unico Si/No nativo di TomTom ancora usato.
    if "linea_atac" in gdf.columns:
        gdf["linea_atac"] = _boolifica_si_no(gdf["linea_atac"])

    # Toponimo: strip.
    if "toponimo" in gdf.columns:
        gdf["toponimo"] = gdf["toponimo"].astype(str).str.strip()
        gdf.loc[gdf["toponimo"].isin(["", "nan", "None"]), "toponimo"] = np.nan

    return gdf


# ---------------------------------------------------------------------------
# Derivate per gli SPF
# ---------------------------------------------------------------------------


def calcola_derivate(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Aggiunge le covariate derivate usate dalla Fase 2 (SPF).

    Nuove colonne:
    - ``log_tgm``: ``log(max(tgm, 1))`` (evita log(0)).
    - ``log_lunghezza``: ``log(lunghezza_m)`` in metri.
    - ``iqr_velocita``: ``v_p75 - v_p25`` (km/h).
    - ``iqr_norm``: ``iqr_velocita / limite_velocita`` (indicatore di
      disomogeneita' delle velocita' rispetto al limite).
    - ``ratio_v85_limite``: ``v_85 / limite_velocita`` (indicatore di
      "aggressivita'" del traffico).
    - ``eccesso_v85``: ``max(v_85 - limite_velocita, 0)`` (km/h oltre il
      limite al 85esimo percentile).
    """
    gdf = gdf.copy()

    if "tgm" in gdf.columns:
        tgm_safe = gdf["tgm"].clip(lower=1.0)
        gdf["log_tgm"] = np.log(tgm_safe)

    if "lunghezza_m" in gdf.columns:
        lung_safe = gdf["lunghezza_m"].clip(lower=1e-3)
        gdf["log_lunghezza"] = np.log(lung_safe)

    if "v_p75" in gdf.columns and "v_p25" in gdf.columns:
        gdf["iqr_velocita"] = gdf["v_p75"] - gdf["v_p25"]

    if "iqr_velocita" in gdf.columns and "limite_velocita" in gdf.columns:
        with np.errstate(divide="ignore", invalid="ignore"):
            gdf["iqr_norm"] = gdf["iqr_velocita"] / gdf["limite_velocita"]

    if "v_85" in gdf.columns and "limite_velocita" in gdf.columns:
        with np.errstate(divide="ignore", invalid="ignore"):
            gdf["ratio_v85_limite"] = gdf["v_85"] / gdf["limite_velocita"]
        gdf["eccesso_v85"] = (gdf["v_85"] - gdf["limite_velocita"]).clip(lower=0)

    return gdf


# ---------------------------------------------------------------------------
# Pulizia geometrica e riproiezione
# ---------------------------------------------------------------------------


def pulisci_geometrie(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Rimuove archi con geometria nulla, vuota o invalida.

    Tenta un ``buffer(0)`` sugli invalidi prima di scartarli; in pratica
    per le ``MultiLineString`` l'operazione e' un no-op e gli invalidi
    vanno comunque scartati, ma e' coerente con il resto della pipeline.
    """
    n_prima = len(gdf)
    mask_nulla = gdf.geometry.isna() | gdf.geometry.is_empty
    if mask_nulla.any():
        log.warning("Scarto %d archi con geometria nulla/vuota", int(mask_nulla.sum()))
        gdf = gdf.loc[~mask_nulla].copy()

    mask_invalida = ~gdf.geometry.is_valid
    if mask_invalida.any():
        log.warning(
            "Tento il fix di %d archi con geometria invalida", int(mask_invalida.sum())
        )
        gdf.loc[mask_invalida, "geometry"] = gdf.loc[mask_invalida, "geometry"].buffer(0)
        ancora_invalide = ~gdf.geometry.is_valid
        if ancora_invalide.any():
            log.warning(
                "Scarto %d archi con geometria ancora invalida dopo il fix",
                int(ancora_invalide.sum()),
            )
            gdf = gdf.loc[~ancora_invalide].copy()

    n_dopo = len(gdf)
    if n_dopo != n_prima:
        log.info("Pulizia geometrica: %d -> %d archi", n_prima, n_dopo)
    return gdf


def riproietta(gdf: gpd.GeoDataFrame, crs_target: str) -> gpd.GeoDataFrame:
    """Riproietta il GeoDataFrame verso ``crs_target``."""
    log.info("Riproiezione rete: %s -> %s", gdf.crs, crs_target)
    return gdf.to_crs(crs_target)


# ---------------------------------------------------------------------------
# Join con il grafo PGTU 2026
# ---------------------------------------------------------------------------


def carica_pgtu(percorso: Path) -> gpd.GeoDataFrame:
    """Carica il grafo PGTU 2026 e normalizza le colonne categoriali.

    Le colonne risultanti sono:
    - ``classifica``: categoria ``S``/``IQ``/``IZ``/``Q`` o NaN se assente
    - ``grande_viabilita``: boolean (``Si``/``No``) con NaN
    - ``tpl``: boolean (``Si``/``No``) con NaN
    - ``nome``: nome strada (string)
    """
    if not percorso.exists():
        raise FileNotFoundError(f"File PGTU non trovato: {percorso}")

    log.info("Caricamento grafo PGTU 2026 da %s", percorso)
    gdf = gpd.read_file(percorso)
    log.info("Caricati %d archi PGTU con CRS %s", len(gdf), gdf.crs)

    if "classifica" in gdf.columns:
        gdf["classifica"] = _pulisci_categoria(gdf["classifica"])
    if "grande_viabilita" in gdf.columns:
        gdf["grande_viabilita"] = _boolifica_si_no(gdf["grande_viabilita"])
    if "tpl" in gdf.columns:
        gdf["tpl"] = _boolifica_si_no(gdf["tpl"])

    return gdf


def _midpoint_linestring(geom: Any) -> Point | None:
    """Restituisce il punto a mezza lunghezza della geometria (lineare).

    Gestisce sia ``LineString`` che ``MultiLineString``: in quest'ultimo
    caso usa ``interpolate(0.5, normalized=True)`` sulla geometria completa,
    che internamente tiene conto della lunghezza cumulata dei segmenti.
    """
    if geom is None or geom.is_empty:
        return None
    try:
        return geom.interpolate(0.5, normalized=True)
    except Exception:  # pragma: no cover (geometria esotica)
        return None


def joina_pgtu(
    gdf_rete: gpd.GeoDataFrame,
    gdf_pgtu: gpd.GeoDataFrame,
    raggio_m: float,
) -> gpd.GeoDataFrame:
    """Aggancia la classificazione PGTU 2026 agli archi TomTom.

    Per ogni arco TomTom calcola il midpoint e trova l'arco PGTU piu' vicino
    entro ``raggio_m`` metri (nel CRS di ``gdf_rete``). Il PGTU viene
    riproiettato on-the-fly se necessario.

    Colonne aggiunte a ``gdf_rete``:
    - ``pgtu_classifica``: category (``S``/``IQ``/``IZ``/``Q`` o NaN)
    - ``grande_viabilita``: boolean (True/False/NaN)
    - ``pgtu_tpl``: boolean (True/False/NaN)
    - ``pgtu_nome``: string, nome strada PGTU associata (utile per debug)
    - ``pgtu_distanza_m``: float, distanza midpoint-arco PGTU in metri
    """
    if gdf_rete.crs is None:
        raise ValueError("gdf_rete deve avere un CRS definito")
    if gdf_pgtu.crs is None:
        raise ValueError("gdf_pgtu deve avere un CRS definito")

    if gdf_pgtu.crs != gdf_rete.crs:
        log.info("Riproiezione PGTU: %s -> %s", gdf_pgtu.crs, gdf_rete.crs)
        gdf_pgtu = gdf_pgtu.to_crs(gdf_rete.crs)

    # Manteniamo solo gli archi PGTU con almeno una informazione utile.
    if "classifica" in gdf_pgtu.columns or "grande_viabilita" in gdf_pgtu.columns:
        maschera_utile = pd.Series(False, index=gdf_pgtu.index)
        if "classifica" in gdf_pgtu.columns:
            maschera_utile |= gdf_pgtu["classifica"].notna()
        if "grande_viabilita" in gdf_pgtu.columns:
            maschera_utile |= gdf_pgtu["grande_viabilita"].notna()
        n_scartati = int((~maschera_utile).sum())
        if n_scartati:
            log.info(
                "PGTU: %d archi senza classifica ne' grande_viabilita' - non usati per il join",
                n_scartati,
            )
        gdf_pgtu = gdf_pgtu.loc[maschera_utile].copy()

    log.info(
        "Join PGTU: %d archi TomTom <-> %d archi PGTU (raggio max %.0f m)",
        len(gdf_rete),
        len(gdf_pgtu),
        raggio_m,
    )

    # Midpoint per ciascun arco TomTom: e' piu' rappresentativo del fatto
    # che l'arco e' "la stessa strada" del PGTU rispetto al minimo vertice-a-vertice.
    midpoints = gdf_rete.geometry.apply(_midpoint_linestring)
    gdf_mid = gpd.GeoDataFrame(
        {"id_arco": gdf_rete["id_arco"].values if "id_arco" in gdf_rete.columns else gdf_rete.index},
        geometry=list(midpoints),
        crs=gdf_rete.crs,
        index=gdf_rete.index,
    )

    # sjoin_nearest richiede che entrambi i gdf abbiano lo stesso CRS (gia' garantito).
    colonne_pgtu = [c for c in ("classifica", "grande_viabilita", "tpl", "nome")
                    if c in gdf_pgtu.columns]
    gdf_pgtu_join = gdf_pgtu[colonne_pgtu + ["geometry"]].copy()

    joined = gpd.sjoin_nearest(
        gdf_mid,
        gdf_pgtu_join,
        how="left",
        max_distance=raggio_m,
        distance_col="pgtu_distanza_m",
    )

    # In caso di pareggi sjoin_nearest puo' duplicare una riga TomTom.
    # Teniamo la prima occorrenza per ciascun indice originale.
    joined = joined[~joined.index.duplicated(keep="first")]

    # Porta i risultati sul gdf di rete.
    gdf_out = gdf_rete.copy()
    gdf_out["pgtu_classifica"] = (
        joined["classifica"].astype("category") if "classifica" in joined.columns else pd.NA
    )
    gdf_out["grande_viabilita"] = (
        joined["grande_viabilita"].astype("boolean")
        if "grande_viabilita" in joined.columns
        else pd.NA
    )
    if "tpl" in joined.columns:
        gdf_out["pgtu_tpl"] = joined["tpl"].astype("boolean")
    if "nome" in joined.columns:
        gdf_out["pgtu_nome"] = joined["nome"].astype("string")
    gdf_out["pgtu_distanza_m"] = joined["pgtu_distanza_m"].astype(float)

    n_matchati = int(gdf_out["pgtu_classifica"].notna().sum())
    n_gv = int(gdf_out["grande_viabilita"].fillna(False).sum())
    log.info(
        "Join PGTU completato: %d archi con classifica, %d archi di grande viabilita'",
        n_matchati,
        n_gv,
    )
    return gdf_out


def classifica_extraurbane(
    gdf_rete: gpd.GeoDataFrame,
    config: dict[str, Any],
    raggio_m: float = 30.0,
) -> gpd.GeoDataFrame:
    """Classifica gli archi TomTom come extraurbane CdR o altri enti.

    Per ogni arco TomTom calcola il midpoint e verifica se ricade entro
    ``raggio_m`` da una geometria nei due GeoJSON.  Aggiunge le colonne
    booleane ``is_extraurbana_cdr`` e ``is_extraurbana_altri_enti``.
    Se i file non esistono le colonne vengono inizializzate a False.
    """
    gdf_out = gdf_rete.copy()
    gdf_out["is_extraurbana_cdr"] = False
    gdf_out["is_extraurbana_altri_enti"] = False

    paths_raw = config.get("paths", {}).get("raw", {})

    for chiave, colonna in [
        ("strade_extraurbane_cdr", "is_extraurbana_cdr"),
        ("strade_extraurbane_altri_enti", "is_extraurbana_altri_enti"),
    ]:
        rel = paths_raw.get(chiave)
        if not rel:
            continue
        percorso = RADICE_PROGETTO / rel
        if not percorso.exists():
            log.warning("File %s non trovato: %s — salto classificazione", chiave, percorso)
            continue

        gdf_ext = gpd.read_file(percorso)
        log.info("Caricato %s: %d geometrie, CRS %s", chiave, len(gdf_ext), gdf_ext.crs)
        if gdf_ext.crs != gdf_out.crs:
            gdf_ext = gdf_ext.to_crs(gdf_out.crs)

        midpoints = gdf_out.geometry.apply(_midpoint_linestring)
        gdf_mid = gpd.GeoDataFrame(
            {"_idx": gdf_out.index},
            geometry=list(midpoints),
            crs=gdf_out.crs,
            index=gdf_out.index,
        )

        joined = gpd.sjoin_nearest(
            gdf_mid,
            gdf_ext[["geometry"]],
            how="left",
            max_distance=raggio_m,
            distance_col="_dist",
        )
        joined = joined[~joined.index.duplicated(keep="first")]
        matchati = joined["_dist"].notna()
        gdf_out.loc[matchati, colonna] = True
        n_match = int(matchati.sum())
        log.info(
            "Classificazione %s: %d archi su %d (raggio %.0f m)",
            colonna, n_match, len(gdf_out), raggio_m,
        )

    return gdf_out


# ---------------------------------------------------------------------------
# Riassunto e salvataggio
# ---------------------------------------------------------------------------


def riassumi(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Produce un riassunto di qualita' della rete preparata."""
    riassunto: dict[str, Any] = {
        "n_archi": int(len(gdf)),
        "lunghezza_km_totale": float(gdf["lunghezza_m"].sum() / 1000.0)
        if "lunghezza_m" in gdf.columns
        else 0.0,
        "tgm_mediano": float(gdf["tgm"].median())
        if "tgm" in gdf.columns
        else float("nan"),
        "n_tgm_nulli": int(gdf["tgm"].isna().sum())
        if "tgm" in gdf.columns
        else 0,
        "n_grande_viabilita": int(gdf["grande_viabilita"].fillna(False).sum())
        if "grande_viabilita" in gdf.columns
        else 0,
        "n_linea_atac": int(gdf["linea_atac"].fillna(False).sum())
        if "linea_atac" in gdf.columns
        else 0,
    }
    if "pgtu_classifica" in gdf.columns:
        riassunto["n_per_pgtu_classifica"] = (
            gdf["pgtu_classifica"].value_counts(dropna=False).astype(int).to_dict()
        )
    if "pgtu_tpl" in gdf.columns:
        riassunto["n_pgtu_tpl"] = int(gdf["pgtu_tpl"].fillna(False).sum())
    if "classe_frc" in gdf.columns:
        riassunto["n_per_frc"] = (
            gdf["classe_frc"].value_counts(dropna=False).astype(int).to_dict()
        )
    return riassunto


def salva_geopackage(gdf: gpd.GeoDataFrame, percorso: Path) -> None:
    """Salva la rete preparata in GeoPackage."""
    percorso.parent.mkdir(parents=True, exist_ok=True)
    if percorso.exists():
        percorso.unlink()
    log.info("Salvataggio rete preparata: %s (%d archi)", percorso, len(gdf))
    gdf.to_file(percorso, driver="GPKG", layer="rete_prep")


# ---------------------------------------------------------------------------
# Semafori (Task 0.3 - lato dati sorgente)
# ---------------------------------------------------------------------------

#: Mappatura colonne del file ``semafori.gpkg`` fornito dal Comune di Roma.
MAPPATURA_COLONNE_SEMAFORI: dict[str, str] = {
    "COD_IMP": "id_impianto",
    "TIPO": "tipo",
    "VIA_1": "via_1",
    "VIA_2": "via_2",
    "VIA_3": "via_3",
    "CIV": "civico",
    "CIRC": "municipio_romano",
}


def carica_semafori(percorso: Path) -> gpd.GeoDataFrame:
    """Carica il GeoPackage dei semafori.

    Il file sorgente contiene tutti gli impianti semaforici di Roma con:
    - ``COD_IMP``: identificativo univoco (stringa zero-padded)
    - ``TIPO``: ``V`` (veicolare) o ``P`` (pedonale)
    - ``VIA_1`` / ``VIA_2`` / ``VIA_3``: toponimi delle strade incrociate
    - ``CIV``: civico (valorizzato solo per i semafori pedonali)
    - ``CIRC``: municipio in numeri romani
    - ``Long`` / ``Lat``: coordinate geografiche (duplicano la geometria)
    """
    if not percorso.exists():
        raise FileNotFoundError(f"File semafori non trovato: {percorso}")
    log.info("Caricamento semafori da %s", percorso)
    gdf = gpd.read_file(percorso)
    log.info("Caricati %d semafori con CRS %s", len(gdf), gdf.crs)
    return gdf


def standardizza_semafori(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Rinomina le colonne dei semafori, normalizza i toponimi e deriva i flag.

    Nuove colonne calcolate:
    - ``is_veicolare``: boolean, ``True`` se ``tipo == 'V'`` (gli impianti
      pedonali puri non vengono usati come intersezione semaforizzata).
    - ``n_bracci``: numero di toponimi non nulli tra ``via_1``, ``via_2``,
      ``via_3`` (stima del numero di strade convergenti all'impianto).

    I toponimi vengono normalizzati con :func:`src.s00_pulizia_incidenti.normalizza_nome_strada`
    per essere coerenti con quelli del database incidenti nelle fasi di
    matching successive.
    """
    from src.s00_pulizia_incidenti import normalizza_nome_strada

    gdf = gdf.rename(
        columns={k: v for k, v in MAPPATURA_COLONNE_SEMAFORI.items() if k in gdf.columns}
    )

    # Droppa Long/Lat: duplicano la geometria e creano rumore.
    for col_extra in ("Long", "Lat"):
        if col_extra in gdf.columns:
            gdf = gdf.drop(columns=[col_extra])

    # Tipo: strip, uppercase.
    if "tipo" in gdf.columns:
        gdf["tipo"] = gdf["tipo"].astype(str).str.strip().str.upper().astype("category")
        gdf["is_veicolare"] = (gdf["tipo"] == "V").astype("boolean")

    # Toponimi: strip + normalizzazione (Via TIBERINA -> Via Tiberina).
    for col in ("via_1", "via_2", "via_3"):
        if col in gdf.columns:
            gdf[col] = gdf[col].apply(normalizza_nome_strada)

    # n_bracci: conta i toponimi non nulli.
    colonne_via = [c for c in ("via_1", "via_2", "via_3") if c in gdf.columns]
    if colonne_via:
        gdf["n_bracci"] = gdf[colonne_via].notna().sum(axis=1).astype("Int64")

    # Municipio romano: strip, uppercase (I, II, ..., XV).
    if "municipio_romano" in gdf.columns:
        gdf["municipio_romano"] = (
            gdf["municipio_romano"].astype(str).str.strip().str.upper().astype("category")
        )

    # Id impianto: strip (zero-padded string).
    if "id_impianto" in gdf.columns:
        gdf["id_impianto"] = gdf["id_impianto"].astype(str).str.strip()

    return gdf


def valida_semafori(gdf: gpd.GeoDataFrame) -> dict[str, int]:
    """Controlli di sanita' sul dataset dei semafori."""
    diagnosi = {
        "n_totali": int(len(gdf)),
        "n_geom_nulle": int(gdf.geometry.isna().sum()),
        "n_geom_vuote": int(gdf.geometry.is_empty.sum()),
        "n_duplicati_id": 0,
    }
    if "id_impianto" in gdf.columns:
        diagnosi["n_duplicati_id"] = int(gdf["id_impianto"].duplicated().sum())
    elif "COD_IMP" in gdf.columns:
        diagnosi["n_duplicati_id"] = int(gdf["COD_IMP"].duplicated().sum())

    for chiave, valore in diagnosi.items():
        if chiave == "n_totali":
            log.info("Validazione semafori: %d record totali", valore)
        elif valore > 0:
            log.warning("Validazione semafori: %s = %d", chiave, valore)
    return diagnosi


def riassumi_semafori(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Produce un riassunto del dataset semafori."""
    riassunto: dict[str, Any] = {"n_totali": int(len(gdf))}
    if "tipo" in gdf.columns:
        riassunto["n_per_tipo"] = (
            gdf["tipo"].value_counts(dropna=False).astype(int).to_dict()
        )
    if "is_veicolare" in gdf.columns:
        riassunto["n_veicolari"] = int(gdf["is_veicolare"].fillna(False).sum())
    if "n_bracci" in gdf.columns:
        riassunto["n_per_bracci"] = (
            gdf["n_bracci"].value_counts(dropna=False).astype(int).to_dict()
        )
    return riassunto


def salva_semafori_geopackage(gdf: gpd.GeoDataFrame, percorso: Path) -> None:
    """Salva il dataset semafori in GeoPackage."""
    percorso.parent.mkdir(parents=True, exist_ok=True)
    if percorso.exists():
        percorso.unlink()
    log.info("Salvataggio semafori: %s (%d record)", percorso, len(gdf))
    gdf.to_file(percorso, driver="GPKG", layer="semafori_prep")


def prepara_semafori(config: dict[str, Any]) -> gpd.GeoDataFrame:
    """Pipeline completa di preparazione dei semafori."""
    percorso_rel = config["paths"]["raw"]["semafori"]
    percorso = RADICE_PROGETTO / percorso_rel
    gdf = carica_semafori(percorso)

    valida_semafori(gdf)
    gdf = standardizza_semafori(gdf)

    crs_target = config["crs"]["metrico"]
    gdf = riproietta(gdf, crs_target=crs_target)

    # Correzione offset sistematico rispetto alla rete TomTom.
    # Calcolato empiricamente: mediana dello scostamento (dx, dy) tra
    # semafori e punto piu' vicino sulla rete = (0.9, 6.4) m.
    offset = config.get("correzioni", {}).get("offset_semafori_m")
    if offset:
        dx = float(offset.get("dx", 0))
        dy = float(offset.get("dy", 0))
        gdf["geometry"] = gdf.geometry.translate(xoff=dx, yoff=dy)
        log.info("Applicata correzione offset semafori: dx=%.1f m, dy=%.1f m", dx, dy)

    return gdf


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def prepara(config: dict[str, Any]) -> gpd.GeoDataFrame:
    """Esegue l'intera preparazione della rete TomTom + join PGTU 2026."""
    percorso_rel = config["paths"]["raw"]["rete_tomtom"]
    percorso = RADICE_PROGETTO / percorso_rel
    gdf = carica_rete_tomtom(percorso)

    valida_rete(gdf)
    gdf = standardizza_colonne(gdf)
    gdf = pulisci_geometrie(gdf)
    gdf = calcola_derivate(gdf)

    crs_target = config["crs"]["metrico"]
    gdf = riproietta(gdf, crs_target=crs_target)

    # Join con il grafo PGTU 2026 (classifica, grande viabilita', TPL).
    percorso_pgtu_rel = config["paths"]["raw"]["rete_pgtu"]
    percorso_pgtu = RADICE_PROGETTO / percorso_pgtu_rel
    gdf_pgtu = carica_pgtu(percorso_pgtu)
    raggio_pgtu = float(config["matching"]["raggio_associazione_pgtu"])
    gdf = joina_pgtu(gdf, gdf_pgtu, raggio_m=raggio_pgtu)

    # Classificazione strade extraurbane (CdR e altri enti).
    gdf = classifica_extraurbane(gdf, config, raggio_m=raggio_pgtu)

    return gdf


def main(config: dict[str, Any]) -> None:
    """Entry point dello step: prepara la rete e salva l'output."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    gdf = prepara(config)

    riassunto = riassumi(gdf)
    log.info("Riassunto rete preparata:")
    for chiave, valore in riassunto.items():
        log.info("  %s: %s", chiave, valore)

    output_rel = config["paths"]["interim"]["rete_tomtom_prep"]
    output = RADICE_PROGETTO / output_rel
    salva_geopackage(gdf, output)

    # --- Preparazione semafori (Task 0.3 lato dati sorgente) ---
    gdf_sem = prepara_semafori(config)

    riassunto_sem = riassumi_semafori(gdf_sem)
    log.info("Riassunto semafori preparati:")
    for chiave, valore in riassunto_sem.items():
        log.info("  %s: %s", chiave, valore)

    output_sem_rel = config["paths"]["interim"]["semafori_prep"]
    output_sem = RADICE_PROGETTO / output_sem_rel
    salva_semafori_geopackage(gdf_sem, output_sem)


if __name__ == "__main__":
    main(carica_config())
