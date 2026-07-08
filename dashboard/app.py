"""Entry point della dashboard Dash — Black Point Roma (Fase 5).

Carica i dati da ``data/processed/priorita_finale.gpkg``, costruisce
il layout e registra i callback.  Per avviare::

    python dashboard/app.py            # sviluppo (debug=True, porta 8050)
    python dashboard/app.py --port 8080 --no-debug

"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from dash import Dash

log = logging.getLogger("dashboard")

_RADICE = Path(__file__).resolve().parent.parent

# Permette il lancio diretto `python dashboard/app.py` (oltre a
# `python -m dashboard.app`): la radice del repo deve stare in sys.path
# per gli import `dashboard.*` e `src.*`.
if str(_RADICE) not in sys.path:
    sys.path.insert(0, str(_RADICE))


def _extract_line_coords(geom) -> list[tuple[float, float]]:
    """Extract (lon, lat) pairs from a LineString/MultiLineString.

    For MultiLineString, sub-lines are separated by (None, None).
    """
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "MultiLineString":
        coords: list[tuple[float, float]] = []
        for i, line in enumerate(geom.geoms):
            if i > 0:
                coords.append((None, None))
            coords.extend([(c[0], c[1]) for c in line.coords])
        return coords
    if geom.geom_type == "LineString":
        return [(c[0], c[1]) for c in geom.coords]
    if geom.geom_type == "Point":
        return [(geom.x, geom.y)]
    return []


def _carica_dati(gpkg_path: Path) -> pd.DataFrame:
    """Carica segmenti e intersezioni, calcola centroidi/coordinate e unisce.

    Se il GeoPackage non esiste, tenta il fallback sui GeoJSON in
    data/processed/segmenti.geojson e intersezioni.geojson.
    """
    processed = gpkg_path.parent

    geojson_seg = processed / "segmenti.geojson"
    geojson_int = processed / "intersezioni.geojson"

    if not gpkg_path.exists():
        if geojson_seg.exists() and geojson_int.exists():
            log.info("GeoPackage non trovato, carico dai GeoJSON...")
            gdf_seg = gpd.read_file(geojson_seg)
            gdf_int = gpd.read_file(geojson_int)
        else:
            raise FileNotFoundError(
                f"Nessun dato trovato. Attesi:\n"
                f"  {gpkg_path}\noppure:\n"
                f"  {geojson_seg}\n  {geojson_int}"
            )
    else:
        log.info("Caricamento dati da %s", gpkg_path)
        gdf_seg = gpd.read_file(gpkg_path, layer="segmenti")
        gdf_int = gpd.read_file(gpkg_path, layer="intersezioni")

    _wgs = "EPSG:4326"

    # --- Segments: extract line coords + centroids in WGS84 ---
    gdf_seg_wgs = gdf_seg.to_crs(_wgs)
    gdf_seg["geom_coords"] = gdf_seg_wgs.geometry.apply(_extract_line_coords)
    centr_seg = gdf_seg_wgs.geometry.centroid
    gdf_seg["lon"] = centr_seg.x
    gdf_seg["lat"] = centr_seg.y

    # --- Intersections: points only ---
    gdf_int_wgs = gdf_int.to_crs(_wgs)
    centr_int = gdf_int_wgs.geometry.centroid
    gdf_int["lon"] = centr_int.x
    gdf_int["lat"] = centr_int.y

    df_seg = pd.DataFrame(gdf_seg.drop(columns="geometry"))
    df_int = pd.DataFrame(gdf_int.drop(columns="geometry"))
    df = pd.concat([df_seg, df_int], ignore_index=True)

    if "toponimo" in df.columns:
        df["toponimo"] = df["toponimo"].fillna("")
    else:
        df["toponimo"] = ""

    if "is_semaforizzata" not in df.columns:
        df["is_semaforizzata"] = False

    log.info("Dati caricati: %d record totali", len(df))
    return df


def _carica_equita(processed_dir: Path) -> dict | None:
    """Carica i dati del modulo Equita' (s08) se disponibili.

    Ritorna ``{"df": ..., "geojson": ..., "indici": ...}`` con le sole
    sezioni abitate, geometrie semplificate (~25 m) in WGS84 pronte per
    la choropleth, oppure None se s08 non e' stato eseguito.
    """
    import json

    gpkg = processed_dir / "equita.gpkg"
    if not gpkg.exists():
        log.info("equita.gpkg non trovato: tab Equita' disabilitata.")
        return None

    gdf = gpd.read_file(gpkg, layer="sezioni")
    gdf = gdf[~gdf["pop_zero"].astype(bool)].copy()
    gdf["SEZ21_ID"] = gdf["SEZ21_ID"].astype("int64")
    gdf = gdf.set_index("SEZ21_ID", drop=False)

    # Geometrie semplificate per il rendering (25 m nel CRS metrico).
    gdf["geometry"] = gdf.geometry.simplify(25)
    gdf_wgs = gdf.to_crs("EPSG:4326")
    geojson = json.loads(gdf_wgs[["geometry"]].to_json())

    indici_path = processed_dir / "equita_indici.json"
    indici = json.loads(indici_path.read_text()) if indici_path.exists() else {}

    df = pd.DataFrame(gdf.drop(columns="geometry"))
    log.info("Equita': %d sezioni abitate caricate", len(df))
    return {"df": df, "geojson": geojson, "indici": indici}


def _carica_scenari(processed_dir: Path) -> dict | None:
    """Carica gli scenari MCLP pre-calcolati (s09), se disponibili."""
    import json

    parquet = processed_dir / "scenari.parquet"
    indici_path = processed_dir / "scenari_indici.json"
    if not parquet.exists() or not indici_path.exists():
        log.info("Scenari non trovati: tab Scenari disabilitata.")
        return None
    scelte = pd.read_parquet(parquet)
    indici = json.loads(indici_path.read_text())
    log.info("Scenari: %d scelte su %d punti della frontiera",
             len(scelte), len(indici.get("frontiera", [])))
    return {"scelte": scelte, "indici": indici}


def crea_app(gpkg_path: Path | None = None) -> Dash:
    """Crea e configura l'applicazione Dash."""
    from dashboard.callbacks import registra_callbacks
    from dashboard.layouts import costruisci_layout

    if gpkg_path is None:
        gpkg_path = _RADICE / "data" / "processed" / "priorita_finale.gpkg"

    df = _carica_dati(gpkg_path)
    equita = _carica_equita(gpkg_path.parent)
    scenari = _carica_scenari(gpkg_path.parent)

    app = Dash(
        __name__,
        title="Black Point Roma",
        suppress_callback_exceptions=True,
    )
    app.layout = costruisci_layout()
    registra_callbacks(app, df, equita=equita, scenari=scenari)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Dashboard Black Point Roma")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--no-debug", action="store_true")
    parser.add_argument("--gpkg", type=Path, default=None,
                        help="Percorso al GeoPackage priorita_finale.gpkg")
    args = parser.parse_args()

    app = crea_app(args.gpkg)
    app.run(
        debug=not args.no_debug,
        port=args.port,
        host="0.0.0.0",
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
