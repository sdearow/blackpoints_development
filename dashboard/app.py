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

# Radice del repo (due livelli sopra dashboard/).
_RADICE = Path(__file__).resolve().parent.parent


def _carica_dati(gpkg_path: Path) -> pd.DataFrame:
    """Carica segmenti e intersezioni, calcola i centroidi e unisce."""
    log.info("Caricamento dati da %s", gpkg_path)

    gdf_seg = gpd.read_file(gpkg_path, layer="segmenti")
    gdf_int = gpd.read_file(gpkg_path, layer="intersezioni")

    # Centroidi calcolati in CRS metrico, poi convertiti in WGS84.
    centr_seg = gdf_seg.geometry.centroid.to_crs("EPSG:4326")
    centr_int = gdf_int.geometry.centroid.to_crs("EPSG:4326") \
        if gdf_int.crs and gdf_int.crs.to_epsg() != 4326 \
        else gdf_int.geometry

    gdf_seg["lon"] = centr_seg.x
    gdf_seg["lat"] = centr_seg.y
    gdf_int["lon"] = centr_int.x
    gdf_int["lat"] = centr_int.y

    df_seg = pd.DataFrame(gdf_seg.drop(columns="geometry"))
    df_int = pd.DataFrame(gdf_int.drop(columns="geometry"))

    df = pd.concat([df_seg, df_int], ignore_index=True)
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
    app.run(debug=not args.no_debug, port=args.port, host="0.0.0.0")


if __name__ == "__main__":
    main()
