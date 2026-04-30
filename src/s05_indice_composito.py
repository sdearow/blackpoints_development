"""Step 05 - Indice composito di priorita' (Fase 4).

Calcola le quattro componenti dell'indice (eccesso EB pesato, severita',
vulnerabilita' utenti, rischio velocita'), le normalizza su scala 0-100
con percentili robusti, le combina nell'indice composito ``ICP`` con i
pesi configurabili e classifica i siti in fasce di priorita'.
Costruisce inoltre la matrice di rischio 2x2.

Output: ``data/processed/priorita_finale.gpkg``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from src.config import RADICE_PROGETTO, carica_config

log = logging.getLogger("s05_indice_composito")


# =====================================================================
# Task 4.1 — Calcolo delle componenti
# =====================================================================


def calcola_componente_A(df: pd.DataFrame) -> pd.Series:
    """Componente A — eccesso EB pesato (excess_EPDO_i)."""
    return df["excess_EPDO_i"].fillna(0.0).astype(float)


def calcola_componente_B(df: pd.DataFrame, n_min: int = 5) -> pd.Series:
    """Componente B — indice di severita'.

    B_i = (n_mortali + n_feriti) / n_incidenti * credibilita'
    dove credibilita' = min(n_incidenti, n_min) / n_min.
    Smorza i siti con pochi incidenti dove il rapporto e' rumoroso.
    """
    n = df["n_incidenti"].astype(float).clip(lower=1e-9)
    gravi = df["n_mortali"].fillna(0).astype(float) + df["n_feriti"].fillna(0).astype(float)
    ratio = (gravi / n).where(df["n_incidenti"] > 0, 0.0)
    cred = (df["n_incidenti"].clip(upper=n_min).astype(float) / n_min)
    return ratio * cred


def calcola_componente_C(df: pd.DataFrame, n_min: int = 5) -> pd.Series:
    """Componente C — indice di vulnerabilita' utenti.

    C_i = n_pedoni / n_incidenti * credibilita'
    dove credibilita' = min(n_incidenti, n_min) / n_min.
    """
    n = df["n_incidenti"].astype(float).clip(lower=1e-9)
    ratio = (df["n_pedoni"].fillna(0).astype(float) / n).where(
        df["n_incidenti"] > 0, 0.0
    )
    cred = (df["n_incidenti"].clip(upper=n_min).astype(float) / n_min)
    return ratio * cred


def calcola_componente_D_segmenti(df: pd.DataFrame) -> pd.Series:
    """Componente D — dispersione velocita' per segmenti.

    D_i = IQR_norm (dispersione pura, indipendente dai limiti di velocita').
    """
    return df["iqr_norm_medio"].fillna(0).astype(float)


def calcola_componente_D_intersezioni(
    df_int: pd.DataFrame,
    gdf_rete: pd.DataFrame,
    gdf_intersezioni: pd.DataFrame,
) -> pd.Series:
    """Componente D — dispersione velocita' per intersezioni.

    Media pesata per TGM dell'IQR_norm degli archi convergenti.
    """
    # D per ciascun arco = IQR_norm (dispersione pura).
    iqr = gdf_rete.get("iqr_norm", pd.Series(0.0, index=gdf_rete.index)).fillna(0).astype(float)
    d_arco = iqr
    tgm_arco = gdf_rete["tgm"].fillna(0).astype(float)
    arco_d = dict(zip(gdf_rete["id_arco"].values, d_arco.values))
    arco_tgm = dict(zip(gdf_rete["id_arco"].values, tgm_arco.values))

    # Per ogni intersezione, media pesata per TGM.
    result = pd.Series(0.0, index=df_int.index)
    archi_col = gdf_intersezioni.set_index("id_nodo")["archi"]

    for i, id_nodo in enumerate(df_int["id_nodo"]):
        archi_str = archi_col.get(id_nodo, "")
        if isinstance(archi_str, str) and archi_str:
            ids = [int(x) for x in archi_str.split("|")]
        elif isinstance(archi_str, list):
            ids = [int(x) for x in archi_str]
        else:
            ids = []
        if not ids:
            continue
        ds = np.array([arco_d.get(a, 0.0) for a in ids])
        ws = np.array([arco_tgm.get(a, 0.0) for a in ids])
        w_tot = ws.sum()
        if w_tot > 0:
            result.iloc[i] = float(np.average(ds, weights=ws))
    return result


# =====================================================================
# Task 4.2 — Normalizzazione e aggregazione
# =====================================================================


def normalizza_robusta(
    serie: pd.Series,
    p_min: float = 1.0,
    p_max: float = 99.0,
    soglia_zero_pct: float = 50.0,
) -> pd.Series:
    """Normalizza su scala 0-100 usando percentili robusti.

    Se la percentuale di zeri supera ``soglia_zero_pct``, applica la
    normalizzazione zero-inflated: i valori nulli restano 0, quelli
    positivi vengono normalizzati a [1, 100] sulla sotto-distribuzione
    dei soli valori > 0. Questo evita che componenti con molti zeri
    (es. severita' sui segmenti, dove <1% ha feriti gravi) collassino
    tutte a zero.
    """
    vals = serie.dropna()
    if len(vals) == 0:
        return pd.Series(0.0, index=serie.index)

    pct_zero = (vals == 0).sum() / len(vals) * 100.0
    if pct_zero > soglia_zero_pct:
        return _normalizza_zero_inflated(serie, p_min, p_max)

    lo = np.nanpercentile(serie, p_min)
    hi = np.nanpercentile(serie, p_max)
    if hi <= lo:
        return pd.Series(0.0, index=serie.index)
    norm = 100.0 * (serie - lo) / (hi - lo)
    return norm.clip(lower=0.0, upper=100.0)


def _normalizza_zero_inflated(
    serie: pd.Series, p_min: float, p_max: float,
) -> pd.Series:
    """Normalizzazione per distribuzioni zero-inflated.

    Zero -> 0.0, valori positivi -> [1, 100] usando i percentili della
    sotto-distribuzione dei soli valori > 0.
    """
    result = pd.Series(0.0, index=serie.index)
    mask_pos = serie.fillna(0) > 0
    if mask_pos.sum() == 0:
        return result
    positivi = serie.loc[mask_pos]
    lo = np.nanpercentile(positivi, p_min)
    hi = np.nanpercentile(positivi, p_max)
    if hi <= lo:
        result.loc[mask_pos] = 50.0
        return result
    norm = 1.0 + 99.0 * (positivi - lo) / (hi - lo)
    result.loc[mask_pos] = norm.clip(lower=1.0, upper=100.0)
    return result


def calcola_icp(
    df: pd.DataFrame,
    pesi: dict[str, float],
) -> pd.Series:
    """Calcola l'Indice Composito di Priorita' (ICP).

    ICP_i = pA * A_norm + pB * B_norm + pC * C_norm + pD * D_norm
    """
    return (
        float(pesi["eccesso_eb"]) * df["A_norm"]
        + float(pesi["severita"]) * df["B_norm"]
        + float(pesi["vulnerabilita"]) * df["C_norm"]
        + float(pesi["rischio_velocita"]) * df["D_norm"]
    )


def classifica_fasce(
    icp: pd.Series, soglie_percentili: list[float]
) -> pd.Series:
    """Classifica i siti in fasce di priorita' basate su percentili dell'ICP.

    Soglie default: [20, 40, 60, 80] producono 5 fasce:
    monitoraggio, bassa, media, alta, altissima.
    """
    nomi = ["monitoraggio", "bassa", "media", "alta", "altissima"]
    valori_soglia = [np.nanpercentile(icp, p) for p in soglie_percentili]
    condizioni = [
        icp <= valori_soglia[0],
        icp <= valori_soglia[1],
        icp <= valori_soglia[2],
        icp <= valori_soglia[3],
    ]
    return pd.Series(
        np.select(condizioni, nomi[:4], default="altissima"),
        index=icp.index,
    )


# =====================================================================
# Task 4.3 — Matrice di rischio 2×2
# =====================================================================


def classifica_matrice(df: pd.DataFrame) -> pd.Series:
    """Classifica in 4 quadranti (excess_EPDO × severita').

    Asse X: excess_EPDO_i (alto/basso rispetto al 75° percentile)
    Asse Y: B (severita', alto/basso rispetto al 75° percentile)

    I percentili sono calcolati sui soli siti con almeno un incidente,
    altrimenti la massa di zeri sposta le soglie a zero.
    Siti senza incidenti vanno direttamente in Q4 (monitoraggio).
    """
    ha_incidenti = df["n_incidenti"] > 0
    a_pos = df.loc[ha_incidenti, "A"]
    b_pos = df.loc[ha_incidenti, "B"]
    soglia_exc = np.nanpercentile(a_pos, 75) if len(a_pos) > 0 else 0.0
    soglia_sev = np.nanpercentile(b_pos, 75) if len(b_pos) > 0 else 0.0
    alto_exc = df["A"] > soglia_exc
    alto_sev = df["B"] > soglia_sev

    quadrante = pd.Series("Q4_monitoraggio", index=df.index)
    quadrante[alto_exc & alto_sev] = "Q1_intervento_urgente"
    quadrante[alto_exc & ~alto_sev] = "Q2_intervento_programmato"
    quadrante[~alto_exc & alto_sev] = "Q3_indagine_approfondita"
    return quadrante


# =====================================================================
# Assemblaggio e salvataggio
# =====================================================================


def assembla_priorita(
    df: pd.DataFrame,
    tipo_sito: str,
    pesi: dict[str, float],
    soglie_percentili: list[float],
    p_min: float,
    p_max: float,
    soglia_zero_pct: float = 50.0,
) -> pd.DataFrame:
    """Calcola componenti, normalizza, computa ICP e classifica."""
    df = df.copy()

    # Componenti grezze.
    df["A"] = calcola_componente_A(df)
    df["B"] = calcola_componente_B(df)
    df["C"] = calcola_componente_C(df)
    # D deve essere gia' presente nel DataFrame.

    # Normalizzazione robusta (zero-inflated se la componente ha troppi zeri).
    df["A_norm"] = normalizza_robusta(df["A"], p_min, p_max, soglia_zero_pct)
    df["B_norm"] = normalizza_robusta(df["B"], p_min, p_max, soglia_zero_pct)
    df["C_norm"] = normalizza_robusta(df["C"], p_min, p_max, soglia_zero_pct)
    df["D_norm"] = normalizza_robusta(df["D"], p_min, p_max, soglia_zero_pct)

    # ICP e classificazione.
    df["ICP"] = calcola_icp(df, pesi)
    df["fascia_priorita"] = classifica_fasce(df["ICP"], soglie_percentili)
    df["quadrante_rischio"] = classifica_matrice(df)
    df["tipo_sito"] = tipo_sito

    return df


def riassumi_priorita(df: pd.DataFrame) -> dict[str, Any]:
    """Riassunto della classificazione."""
    r: dict[str, Any] = {
        "n_siti": int(len(df)),
        "ICP_mediana": float(df["ICP"].median()),
        "ICP_p90": float(df["ICP"].quantile(0.90)),
        "ICP_max": float(df["ICP"].max()),
    }
    r["fasce"] = df["fascia_priorita"].value_counts().to_dict()
    r["quadranti"] = df["quadrante_rischio"].value_counts().to_dict()
    return r


def salva_priorita(
    gdf: gpd.GeoDataFrame, percorso: Path, layer: str
) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    # Rimuovi colonne lista/dict non serializzabili.
    drop = [c for c in gdf.columns if gdf[c].dtype == object and c not in ("toponimo", "tipo_sito", "fascia_priorita", "quadrante_rischio", "categoria_spf", "spf_categoria", "pgtu_classifica", "classe_frc")]
    gdf_out = gdf.drop(columns=drop, errors="ignore")
    log.info("Salvataggio %s: %s (%d record)", layer, percorso, len(gdf_out))
    gdf_out.to_file(percorso, driver="GPKG", layer=layer)


# =====================================================================
# Pipeline principale
# =====================================================================


def main(config: dict[str, Any]) -> None:
    """Calcola l'indice composito e classifica i siti."""
    import pickle

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Carica EB results.
    eb_base = RADICE_PROGETTO / config["paths"]["processed"]["eb_results"]
    seg_path = eb_base.with_suffix("").with_name(eb_base.stem + "_segmenti.parquet")
    int_path = eb_base.with_suffix("").with_name(eb_base.stem + "_intersezioni.parquet")
    log.info("Caricamento EB segmenti da %s", seg_path)
    df_seg = pd.read_parquet(seg_path)
    log.info("Caricamento EB intersezioni da %s", int_path)
    df_int = pd.read_parquet(int_path)

    # Carica geometrie per output GeoPackage.
    gdf_segmenti = gpd.read_file(
        RADICE_PROGETTO / config["paths"]["interim"]["segmenti"], layer="segmenti"
    )
    gdf_intersezioni = gpd.read_file(
        RADICE_PROGETTO / config["paths"]["interim"]["intersezioni"], layer="intersezioni"
    )
    gdf_rete = gpd.read_file(
        RADICE_PROGETTO / config["paths"]["interim"]["rete_tomtom_prep"], layer="rete_prep"
    )

    # Parametri dal config.
    pesi = config["indice_composito"]["pesi"]
    p_min = float(config["indice_composito"]["percentile_min"])
    p_max = float(config["indice_composito"]["percentile_max"])
    soglia_zero = float(config["indice_composito"].get("soglia_zero_pct", 50.0))
    soglie = [float(s) for s in config["classificazione"]["soglie_percentili"]]

    # Componente D.
    log.info("Calcolo componente D (rischio velocita')...")
    df_seg["D"] = calcola_componente_D_segmenti(df_seg)
    df_int["D"] = calcola_componente_D_intersezioni(df_int, gdf_rete, gdf_intersezioni)

    # Assemblaggio.
    log.info("Assemblaggio indice composito segmenti...")
    df_seg = assembla_priorita(df_seg, "segmento", pesi, soglie, p_min, p_max, soglia_zero)
    log.info("Assemblaggio indice composito intersezioni...")
    df_int = assembla_priorita(df_int, "intersezione", pesi, soglie, p_min, p_max, soglia_zero)

    # Riassunto.
    for nome, df in (("segmenti", df_seg), ("intersezioni", df_int)):
        r = riassumi_priorita(df)
        log.info("Priorita' %s:", nome)
        for k, v in r.items():
            log.info("  %s: %s", k, v)

    # Join con geometrie e salvataggio.
    out_path = RADICE_PROGETTO / config["paths"]["processed"]["priorita_finale"]
    if out_path.exists():
        out_path.unlink()

    geom_seg = gdf_segmenti[["id_segmento", "geometry"]].set_index("id_segmento")
    df_seg = df_seg.set_index("id_segmento")
    df_seg["geometry"] = geom_seg["geometry"]
    gdf_seg = gpd.GeoDataFrame(df_seg, geometry="geometry", crs=gdf_segmenti.crs)
    gdf_seg = gdf_seg.reset_index()
    salva_priorita(gdf_seg, out_path, layer="segmenti")

    geom_int = gdf_intersezioni[["id_nodo", "geometry"]].set_index("id_nodo")
    df_int = df_int.set_index("id_nodo")
    df_int["geometry"] = geom_int["geometry"]
    gdf_int = gpd.GeoDataFrame(df_int, geometry="geometry", crs=gdf_intersezioni.crs)
    gdf_int = gdf_int.reset_index()
    salva_priorita(gdf_int, out_path, layer="intersezioni")

    log.info("Output: %s", out_path)


if __name__ == "__main__":
    main(carica_config())
