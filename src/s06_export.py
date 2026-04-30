"""Step 06 - Export dei risultati per dashboard e reportistica (Fase 5/6).

Prepara i layer in formato GeoJSON (WGS84) per la dashboard Dash,
genera la classifica Excel dei siti con il ranking per ICP,
esporta la mappa cittadina come immagine PNG e produce un report
CSV di sintesi aggregata per fascia e quadrante.

Output:
- ``data/processed/segmenti.geojson``
- ``data/processed/intersezioni.geojson``
- ``reports/classifica_segmenti.xlsx``
- ``reports/classifica_intersezioni.xlsx``
- ``reports/mappa_priorita.png``
- ``reports/sintesi.csv``
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from src.config import RADICE_PROGETTO, carica_config

log = logging.getLogger("s06_export")

COLORI_FASCE = {
    "monitoraggio": "#2ecc71",
    "bassa": "#f1c40f",
    "media": "#e67e22",
    "alta": "#e74c3c",
    "altissima": "#8b0000",
}

ORDINE_FASCE = ["monitoraggio", "bassa", "media", "alta", "altissima"]


# =====================================================================
# Task 5.5a — Export GeoJSON per la dashboard
# =====================================================================


def _colonne_export(gdf: gpd.GeoDataFrame) -> list[str]:
    """Seleziona le colonne rilevanti per l'export GeoJSON."""
    utili = [
        "id_segmento", "id_nodo", "toponimo", "tipo_sito",
        "n_incidenti", "n_mortali", "n_feriti",
        "n_solo_danni", "n_pedoni",
        "EB_i", "excess_i", "excess_EPDO_i",
        "costo_sociale_eur", "costo_sociale_eccesso_eur",
        "A_norm", "B_norm", "C_norm", "D_norm",
        "ICP", "fascia_priorita", "quadrante_rischio",
        "v85_medio", "limite_velocita_medio", "tgm_medio", "lunghezza_m",
        "flusso_entrante", "is_semaforizzata", "n_archi",
        "geometry",
    ]
    return [c for c in utili if c in gdf.columns]


def esporta_geojson(
    gdf: gpd.GeoDataFrame,
    percorso: Path,
    crs_out: str = "EPSG:4326",
) -> None:
    """Esporta un GeoDataFrame in GeoJSON nel CRS di visualizzazione."""
    gdf_out = gdf[_colonne_export(gdf)].copy()
    if gdf_out.crs and str(gdf_out.crs) != crs_out:
        gdf_out = gdf_out.to_crs(crs_out)
    for col in gdf_out.select_dtypes(include=["float64"]).columns:
        gdf_out[col] = gdf_out[col].round(4)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    gdf_out.to_file(percorso, driver="GeoJSON")
    log.info("GeoJSON: %s (%d record)", percorso, len(gdf_out))


# =====================================================================
# Task 5.5b — Classifica Excel
# =====================================================================


def _colonne_excel(df: pd.DataFrame) -> list[str]:
    """Colonne da includere nell'Excel della classifica."""
    utili = [
        "ranking", "id_segmento", "id_nodo", "toponimo", "tipo_sito",
        "fascia_priorita", "quadrante_rischio", "ICP",
        "A_norm", "B_norm", "C_norm", "D_norm",
        "n_incidenti", "n_mortali", "n_feriti",
        "n_solo_danni", "n_pedoni",
        "EB_i", "excess_i", "excess_EPDO_i",
        "costo_sociale_eur", "costo_sociale_eccesso_eur",
        "v85_medio", "limite_velocita_medio", "tgm_medio", "lunghezza_m",
        "flusso_entrante", "is_semaforizzata", "n_archi",
    ]
    return [c for c in utili if c in df.columns]


def esporta_classifica_excel(
    gdf: gpd.GeoDataFrame,
    percorso: Path,
) -> None:
    """Esporta la classifica completa dei siti in Excel, ordinata per ICP."""
    df = pd.DataFrame(gdf.drop(columns="geometry", errors="ignore"))
    df = df.sort_values("ICP", ascending=False).reset_index(drop=True)
    df.insert(0, "ranking", range(1, len(df) + 1))
    df = df[_colonne_excel(df)]
    for col in df.select_dtypes(include=["float64"]).columns:
        df[col] = df[col].round(4)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(percorso, index=False, sheet_name="classifica")
    log.info("Excel: %s (%d record)", percorso, len(df))


# =====================================================================
# Task 5.5c — Mappa cittadina PNG
# =====================================================================


def esporta_mappa_png(
    gdf_seg: gpd.GeoDataFrame,
    gdf_int: gpd.GeoDataFrame,
    percorso: Path,
    dpi: int = 200,
) -> None:
    """Genera una mappa statica dei siti colorati per fascia di priorita'."""
    fig, ax = plt.subplots(1, 1, figsize=(16, 14))

    gdf_seg_wgs = gdf_seg.to_crs("EPSG:4326") if gdf_seg.crs else gdf_seg
    gdf_int_wgs = gdf_int.to_crs("EPSG:4326") if gdf_int.crs else gdf_int

    for fascia in ORDINE_FASCE:
        colore = COLORI_FASCE[fascia]
        mask_seg = gdf_seg_wgs["fascia_priorita"] == fascia
        if mask_seg.any():
            gdf_seg_wgs.loc[mask_seg].plot(
                ax=ax, color=colore, linewidth=0.4, alpha=0.7,
            )
        mask_int = gdf_int_wgs["fascia_priorita"] == fascia
        if mask_int.any():
            gdf_int_wgs.loc[mask_int].plot(
                ax=ax, color=colore, markersize=2, alpha=0.7,
            )

    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color=COLORI_FASCE[f], lw=4, label=f.capitalize())
        for f in ORDINE_FASCE
    ]
    ax.legend(
        handles=legend_elements,
        title="Fascia di priorita'",
        loc="lower left",
        fontsize=8,
        title_fontsize=9,
    )
    ax.set_title(
        "Black Point Roma - Mappa priorita' incidentale",
        fontsize=14, fontweight="bold",
    )
    ax.set_xlabel("Longitudine")
    ax.set_ylabel("Latitudine")
    ax.set_aspect("equal")

    percorso.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(percorso, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    log.info("Mappa PNG: %s (%d dpi)", percorso, dpi)


# =====================================================================
# Task 5.5d — Report di sintesi CSV
# =====================================================================


def genera_sintesi(
    gdf_seg: gpd.GeoDataFrame,
    gdf_int: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Produce un DataFrame di sintesi aggregata per fascia e tipo sito."""
    righe = []
    for nome, gdf in (("segmento", gdf_seg), ("intersezione", gdf_int)):
        for fascia in ORDINE_FASCE:
            mask = gdf["fascia_priorita"] == fascia
            sub = gdf.loc[mask]
            righe.append(
                {
                    "tipo_sito": nome,
                    "fascia_priorita": fascia,
                    "n_siti": int(len(sub)),
                    "n_incidenti_tot": int(sub["n_incidenti"].sum()),
                    "ICP_mediana": float(sub["ICP"].median()) if len(sub) else 0.0,
                    "ICP_max": float(sub["ICP"].max()) if len(sub) else 0.0,
                    "excess_EPDO_tot": float(sub["excess_EPDO_i"].sum()),
                    "costo_sociale_tot_eur": float(
                        sub["costo_sociale_eccesso_eur"].sum()
                    ),
                }
            )
    return pd.DataFrame(righe)


def esporta_sintesi_csv(
    gdf_seg: gpd.GeoDataFrame,
    gdf_int: gpd.GeoDataFrame,
    percorso: Path,
) -> None:
    """Salva la sintesi aggregata in CSV."""
    df_sint = genera_sintesi(gdf_seg, gdf_int)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    df_sint.to_csv(percorso, index=False)
    log.info("Sintesi CSV: %s (%d righe)", percorso, len(df_sint))


# =====================================================================
# Pipeline principale
# =====================================================================


def main(config: dict[str, Any]) -> None:
    """Esporta i risultati per dashboard e reporting."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    priorita_path = RADICE_PROGETTO / config["paths"]["processed"]["priorita_finale"]
    log.info("Caricamento priorita' da %s", priorita_path)
    gdf_seg = gpd.read_file(priorita_path, layer="segmenti")
    gdf_int = gpd.read_file(priorita_path, layer="intersezioni")
    log.info("Caricati: %d segmenti, %d intersezioni", len(gdf_seg), len(gdf_int))

    processed = RADICE_PROGETTO / "data" / "processed"
    reports = RADICE_PROGETTO / "reports"

    esporta_geojson(gdf_seg, processed / "segmenti.geojson")
    esporta_geojson(gdf_int, processed / "intersezioni.geojson")

    esporta_classifica_excel(gdf_seg, reports / "classifica_segmenti.xlsx")
    esporta_classifica_excel(gdf_int, reports / "classifica_intersezioni.xlsx")

    esporta_mappa_png(gdf_seg, gdf_int, reports / "mappa_priorita.png")

    esporta_sintesi_csv(gdf_seg, gdf_int, reports / "sintesi.csv")

    log.info("Export completato.")


if __name__ == "__main__":
    main(carica_config())
