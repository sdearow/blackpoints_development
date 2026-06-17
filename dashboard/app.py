"""Entry point della dashboard Dash — Black Point Roma (Fase 5).

Carica i dati da ``data/processed/priorita_finale.gpkg``, costruisce
il layout e registra i callback.  Per avviare::

    python dashboard/app.py            # sviluppo (debug=True, porta 8050)
    python dashboard/app.py --port 8080 --no-debug

"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from dash import Dash

log = logging.getLogger("dashboard")

_RADICE = Path(__file__).resolve().parent.parent


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


def crea_app(gpkg_path: Path | None = None) -> Dash:
    """Crea e configura l'applicazione Dash."""
    from dashboard.callbacks import registra_callbacks
    from dashboard.layouts import costruisci_layout

    if gpkg_path is None:
        gpkg_path = _RADICE / "data" / "processed" / "priorita_finale.gpkg"

    df = _carica_dati(gpkg_path)

    app = Dash(
        __name__,
        title="Black Point Roma",
        suppress_callback_exceptions=True,
    )
    app.layout = costruisci_layout()
    registra_callbacks(app, df)
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
