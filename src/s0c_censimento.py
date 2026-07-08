"""Step 0c - Ingest del censimento ISTAT 2021 per sezione (WP0/T0.1 del PSS).

Prepara la base socio-demografica del modulo Equita' (WP2):

1. carica le geometrie delle sezioni di censimento 2021 del Comune di Roma
   (``Sezioni_ISTAT.gpkg``, chiave ``SEZ21_ID``) e le riproietta nel CRS
   metrico di lavoro (EPSG:32633 - il file sorgente e' in EPSG:32632);
2. carica gli indicatori per sezione (``Indicatori_ISTAT_Roma.xlsx``,
   tracciato ISTAT 2021 documentato in ``TRACCIATO_FILE_REGIONALI.xlsx``)
   e li filtra al comune configurato;
3. deriva gli indicatori di vulnerabilita' sociale usati dall'indice di
   bisogno (quote su popolazione o su base specifica);
4. joina su ``SEZ21_ID`` e valida: nel dato 2021 le sezioni senza riga di
   indicatori sono esattamente quelle con POP21 = 0 (disabitate).

Nota metodologica: il reddito non e' disponibile a scala di sezione;
istruzione e occupazione fungono da proxy socio-economiche (limite da
dichiarare nel paper).

Output: ``data/interim/censimento_prep.gpkg`` (layer ``sezioni``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from src.config import RADICE_PROGETTO, carica_config

log = logging.getLogger("s0c_censimento")


# Colonne del tracciato ISTAT 2021 usate per derivare gli indicatori.
# Riferimento: TRACCIATO_FILE_REGIONALI.xlsx (in data/raw/censimento/).
COLONNE_TRACCIATO = [
    "SEZ21_ID",
    "P1",                        # popolazione residente totale
    "P14", "P15", "P16",         # eta' <5, 5-9, 10-14
    "P27", "P28", "P29",         # eta' 65-69, 70-74, >74
    "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", "P25", "P26",  # 15-64
    "P83",                       # pop. 9+ anni (base istruzione)
    "P86", "P87", "P88",         # 9+: senza titolo, licenza elementare, licenza media
    "P101",                      # occupati 15-64
    "ST1",                       # stranieri e apolidi residenti - totale
    "PF1",                       # famiglie residenti - totale
]


def carica_sezioni(percorso: Path, crs_target: str) -> gpd.GeoDataFrame:
    """Carica le geometrie delle sezioni e riproietta al CRS di lavoro."""
    log.info("Caricamento sezioni da %s", percorso)
    gdf = gpd.read_file(percorso)
    log.info("Caricate %d sezioni (CRS %s)", len(gdf), gdf.crs)
    if gdf.crs is None:
        raise ValueError("Il GeoPackage delle sezioni non dichiara un CRS.")
    if str(gdf.crs) != crs_target:
        gdf = gdf.to_crs(crs_target)
        log.info("Riproiettato a %s", crs_target)
    # Ripara le geometrie invalide (self-intersection da digitalizzazione):
    # indispensabile per i join spaziali a valle (s08).
    invalide = ~gdf.geometry.is_valid
    if invalide.any():
        gdf.loc[invalide, "geometry"] = gdf.loc[invalide, "geometry"].make_valid()
        log.info("Riparate %d geometrie invalide (make_valid)", int(invalide.sum()))
    # Chiave di join come intero a 64 bit (nel gpkg e' numerica).
    gdf["SEZ21_ID"] = gdf["SEZ21_ID"].astype("int64")
    return gdf


def carica_indicatori(percorso: Path, pro_com: int | None = None) -> pd.DataFrame:
    """Carica il file regionale degli indicatori e filtra al comune.

    ``pro_com``: codice PROCOM del comune (Roma = 58091); None = nessun filtro.
    """
    log.info("Caricamento indicatori da %s", percorso)
    df = pd.read_excel(percorso)
    log.info("Caricate %d righe (%d comuni)", len(df), df["PROCOM"].nunique())
    if pro_com is not None:
        df = df[df["PROCOM"] == int(pro_com)].copy()
        log.info("Filtro PROCOM=%s: %d sezioni", pro_com, len(df))
    mancanti = [c for c in COLONNE_TRACCIATO if c not in df.columns]
    if mancanti:
        raise ValueError(f"Colonne mancanti nel file indicatori: {mancanti}")
    df = df[COLONNE_TRACCIATO].copy()
    df["SEZ21_ID"] = df["SEZ21_ID"].astype("int64")
    return df


def _quota(numeratore: pd.Series, base: pd.Series) -> pd.Series:
    """Quota numeratore/base, 0 dove la base e' nulla o mancante."""
    num = numeratore.fillna(0).astype(float)
    den = base.fillna(0).astype(float)
    out = pd.Series(0.0, index=num.index)
    valido = den > 0
    out.loc[valido] = num.loc[valido] / den.loc[valido]
    return out


def deriva_indicatori(df: pd.DataFrame) -> pd.DataFrame:
    """Deriva gli indicatori di vulnerabilita' sociale per sezione.

    - ``pop_totale``            : P1
    - ``perc_bambini``          : (P14+P15+P16) / P1        (eta' 0-14)
    - ``perc_anziani``          : (P27+P28+P29) / P1        (eta' 65+)
    - ``perc_stranieri``        : ST1 / P1
    - ``perc_istruzione_bassa`` : (P86+P87+P88) / P83       (al piu' licenza media, 9+)
    - ``perc_non_occupati``     : 1 - P101 / pop(15-64)     (proxy occupazionale)

    Le quote sono 0 dove la base e' nulla (sezioni disabitate restano nel
    dataset con flag ``pop_zero``; l'esclusione avviene a valle in s08,
    dove serve, per non perdere copertura territoriale nella mappa).
    """
    out = pd.DataFrame(index=df.index)
    out["SEZ21_ID"] = df["SEZ21_ID"]
    p1 = df["P1"].fillna(0).astype(float)
    out["pop_totale"] = p1
    out["n_famiglie"] = df["PF1"].fillna(0).astype(float)

    bambini = df[["P14", "P15", "P16"]].fillna(0).sum(axis=1)
    anziani = df[["P27", "P28", "P29"]].fillna(0).sum(axis=1)
    pop_15_64 = df[[f"P{i}" for i in range(17, 27)]].fillna(0).sum(axis=1)
    istr_bassa = df[["P86", "P87", "P88"]].fillna(0).sum(axis=1)

    out["n_bambini"] = bambini
    out["n_anziani"] = anziani
    out["n_stranieri"] = df["ST1"].fillna(0).astype(float)

    out["perc_bambini"] = _quota(bambini, p1)
    out["perc_anziani"] = _quota(anziani, p1)
    out["perc_stranieri"] = _quota(df["ST1"], p1)
    out["perc_istruzione_bassa"] = _quota(istr_bassa, df["P83"])
    out["perc_non_occupati"] = (1.0 - _quota(df["P101"], pop_15_64)).clip(0.0, 1.0)
    # Dove non c'e' popolazione 15-64 la quota occupazionale non e' definita:
    # riportala a 0 (non a 1) per non gonfiare la vulnerabilita' dei vuoti.
    out.loc[pop_15_64.fillna(0) <= 0, "perc_non_occupati"] = 0.0
    return out


def joina_sezioni_indicatori(
    gdf_sezioni: gpd.GeoDataFrame,
    df_indicatori: pd.DataFrame,
) -> gpd.GeoDataFrame:
    """Join geometrie <- indicatori su SEZ21_ID, con flag di qualita'.

    - ``pop_zero``       : sezione disabitata (POP21 = 0);
    - ``ha_indicatori``  : la sezione ha una riga negli indicatori ISTAT.
    Le sezioni disabitate restano con indicatori a 0.
    """
    tieni = ["SEZ21_ID", "POP21", "COM_ASC1", "COM_ASC2", "COM_ASC3",
             "SHAPE_Area", "geometry"]
    tieni = [c for c in tieni if c in gdf_sezioni.columns]
    gdf = gdf_sezioni[tieni].merge(df_indicatori, on="SEZ21_ID", how="left")

    gdf["ha_indicatori"] = gdf["pop_totale"].notna()
    gdf["pop_zero"] = gdf["POP21"].fillna(0).astype(float) <= 0

    col_num = [c for c in df_indicatori.columns if c != "SEZ21_ID"]
    gdf[col_num] = gdf[col_num].fillna(0.0)

    gdf["area_km2"] = gdf.geometry.area / 1e6
    gdf["densita_pop_km2"] = _quota(gdf["pop_totale"], gdf["area_km2"])
    return gpd.GeoDataFrame(gdf, geometry="geometry", crs=gdf_sezioni.crs)


def valida_censimento(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Controlli di coerenza; solleva se il dato viola le attese forti."""
    senza_ind_abitate = int((~gdf["ha_indicatori"] & ~gdf["pop_zero"]).sum())
    incoerenti = int(
        (gdf["ha_indicatori"] & (gdf["POP21"].fillna(0) != gdf["pop_totale"])).sum()
    )
    r: dict[str, Any] = {
        "n_sezioni": int(len(gdf)),
        "n_abitate": int((~gdf["pop_zero"]).sum()),
        "n_con_indicatori": int(gdf["ha_indicatori"].sum()),
        "n_abitate_senza_indicatori": senza_ind_abitate,
        "n_pop21_diverso_p1": incoerenti,
        "pop_totale": int(gdf["pop_totale"].sum()),
        "geometrie_invalide": int((~gdf.geometry.is_valid).sum()),
        "perc_bambini_media": round(float(
            gdf.loc[~gdf["pop_zero"], "perc_bambini"].mean()), 4),
        "perc_anziani_media": round(float(
            gdf.loc[~gdf["pop_zero"], "perc_anziani"].mean()), 4),
        "perc_stranieri_media": round(float(
            gdf.loc[~gdf["pop_zero"], "perc_stranieri"].mean()), 4),
    }
    if senza_ind_abitate > 0:
        log.warning(
            "%d sezioni abitate senza indicatori: copertura ISTAT incompleta.",
            senza_ind_abitate,
        )
    return r


def salva(gdf: gpd.GeoDataFrame, percorso: Path) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    if percorso.exists():
        percorso.unlink()
    gdf.to_file(percorso, driver="GPKG", layer="sezioni")
    log.info("Salvato %s (%d sezioni)", percorso, len(gdf))


def main(config: dict[str, Any]) -> None:
    """Prepara il layer censuario per il modulo Equita'."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    cfg = config.get("censimento", {})
    crs_target = config["crs"]["metrico"]

    gdf_sez = carica_sezioni(
        RADICE_PROGETTO / config["paths"]["raw"]["censimento_sezioni"], crs_target
    )
    df_ind = carica_indicatori(
        RADICE_PROGETTO / config["paths"]["raw"]["censimento_indicatori"],
        pro_com=cfg.get("pro_com"),
    )
    df_der = deriva_indicatori(df_ind)
    gdf = joina_sezioni_indicatori(gdf_sez, df_der)

    r = valida_censimento(gdf)
    log.info("Validazione censimento:")
    for k, v in r.items():
        log.info("  %s: %s", k, v)
    if r["n_abitate_senza_indicatori"] > 0.01 * r["n_abitate"]:
        raise ValueError(
            "Piu' dell'1% delle sezioni abitate e' senza indicatori: "
            "verificare che il file indicatori copra il comune."
        )

    salva(gdf, RADICE_PROGETTO / config["paths"]["interim"]["censimento_prep"])


if __name__ == "__main__":
    main(carica_config())
