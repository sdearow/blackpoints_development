"""Step 0d - Ingest del database interventi/progetti (WP0/T0.2 del PSS).

Unifica le sorgenti eterogenee del database progetti (in divenire) in un
unico layer normalizzato per i moduli Equita' (dotazione), Ottimizzazione
e Before-after. Il registro delle sorgenti vive in ``config.yaml`` ->
``interventi.sorgenti``: aggiungere una nuova tipologia non richiede
modifiche al codice.

Schema normalizzato di output (``data/interim/interventi_prep.gpkg``):

- ``id_intervento``     : "{stem_file}:{progressivo}" (stabile finche' la
                          sorgente non viene riordinata);
- ``tipo``              : tipologia (velox, isola_ambientale, ...);
- ``nome``              : denominazione leggibile (campo configurabile);
- ``fase``              : normalizzata in {pianificato, in_corso,
                          realizzato, da_definire} via ``mappa_fase``;
- ``fase_orig``         : valore grezzo della sorgente (audit);
- ``municipio``         : ove disponibile;
- ``data_attivazione``  : per ora il placeholder di config (2025-01-01);
- ``data_stato``        : "placeholder" | "confermata" - le date reali
                          arrivano via ``date_interventi.csv`` (override
                          per id_intervento; possono essere future per i
                          progetti non ancora attuati);
- ``raggio_influenza_m``: default per tipo (0 per geometrie areali/lineari
                          dove conta l'impronta, >0 per i puntuali);
- ``geometry``          : puntuale, lineare o areale, nel CRS metrico.

Genera anche ``reports/interventi_da_datare.csv``: il template che si puo'
compilare con le date man mano che si consolidano.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from src.config import RADICE_PROGETTO, carica_config

log = logging.getLogger("s0d_interventi")

FASI_VALIDE = {"pianificato", "in_corso", "realizzato", "da_definire"}


def _id_stabile(geom: Any, stem: str) -> str:
    """Id content-based: hash della geometria (WKB con precisione 0.1 m).

    Stabile al riordino delle righe e agli edit degli attributi della
    sorgente: cambia solo se cambia la geometria. Indispensabile perche'
    le date confermate nel CSV di override sono agganciate a questi id
    (gli id nativi delle sorgenti sono quasi tutti non univoci o nulli).
    """
    import hashlib

    import shapely

    g = shapely.set_precision(geom, 0.1)
    h = hashlib.sha1(shapely.to_wkb(g)).hexdigest()[:10]
    return f"{stem}:{h}"


def carica_sorgente(
    cfg_sorgente: dict[str, Any],
    progetti_dir: Path,
    crs_target: str,
) -> gpd.GeoDataFrame:
    """Carica e normalizza una singola sorgente del registro.

    ``cfg_sorgente``: file, tipo, e opzionali layer / campo_nome /
    campo_fase / campo_municipio.
    """
    percorso = progetti_dir / cfg_sorgente["file"]
    layer = cfg_sorgente.get("layer")
    gdf = gpd.read_file(percorso, layer=layer) if layer else gpd.read_file(percorso)

    if gdf.crs is None:
        raise ValueError(f"{percorso.name}: CRS non dichiarato")
    if str(gdf.crs) != crs_target:
        gdf = gdf.to_crs(crs_target)

    invalide = ~gdf.geometry.is_valid
    if invalide.any():
        gdf.loc[invalide, "geometry"] = gdf.loc[invalide, "geometry"].make_valid()

    stem = Path(cfg_sorgente["file"]).stem
    out = gpd.GeoDataFrame(index=gdf.index, geometry=gdf.geometry, crs=gdf.crs)
    out["id_intervento"] = [_id_stabile(g, stem) for g in gdf.geometry]
    # Geometrie identiche nella stessa sorgente (duplicati veri):
    # disambigua con un progressivo, avvisando (solo tra loro l'ordine
    # delle righe torna a contare).
    dup = out["id_intervento"].duplicated(keep=False)
    if dup.any():
        log.warning(
            "%s: %d geometrie duplicate, id disambiguati con progressivo",
            cfg_sorgente["file"], int(dup.sum()),
        )
        prog = out.groupby("id_intervento").cumcount()
        out.loc[dup, "id_intervento"] = (
            out.loc[dup, "id_intervento"] + "-" + (prog[dup] + 1).astype(str)
        )
    out["tipo"] = cfg_sorgente["tipo"]
    out["fonte"] = cfg_sorgente["file"]

    campo_nome = cfg_sorgente.get("campo_nome")
    out["nome"] = (
        gdf[campo_nome].astype(str).replace({"None": None, "nan": None})
        if campo_nome and campo_nome in gdf.columns
        else None
    )

    campo_fase = cfg_sorgente.get("campo_fase")
    out["fase_orig"] = (
        gdf[campo_fase].astype(str).replace({"None": None, "nan": None})
        if campo_fase and campo_fase in gdf.columns
        else None
    )

    campo_mun = cfg_sorgente.get("campo_municipio")
    out["municipio"] = (
        pd.to_numeric(gdf[campo_mun], errors="coerce")
        if campo_mun and campo_mun in gdf.columns
        else np.nan
    )
    return out


def normalizza_fase(
    fase_orig: pd.Series, mappa_fase: dict[str, str]
) -> pd.Series:
    """Mappa i valori grezzi di fase sullo schema normalizzato.

    Best effort dichiarato: il database e' in divenire e molte sorgenti
    usano codici numerici non ancora decodificati -> ``da_definire``.
    Il matching e' case-insensitive sulle chiavi di ``mappa_fase``.
    """
    mappa = {str(k).strip().lower(): v for k, v in mappa_fase.items()}
    if not set(mappa.values()) <= FASI_VALIDE:
        sconosciute = set(mappa.values()) - FASI_VALIDE
        raise ValueError(f"mappa_fase contiene fasi non valide: {sconosciute}")

    def _mappa(v: Any) -> str:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "da_definire"
        return mappa.get(str(v).strip().lower(), "da_definire")

    return fase_orig.map(_mappa)


def applica_date(
    gdf: gpd.GeoDataFrame,
    data_placeholder: str,
    percorso_override: Path | None,
) -> gpd.GeoDataFrame:
    """Assegna la data di attivazione: placeholder per tutti, poi
    override dal CSV ``date_interventi.csv`` dove presente.

    Il CSV di override ha colonne ``id_intervento``, ``data_attivazione``
    (ISO, anche futura per i progetti non attuati) e opzionali ``fase``
    e ``data_fine`` (fine lavori: il before-after fa partire il "dopo"
    da qui, escludendo il periodo di cantiere).
    """
    gdf = gdf.copy()
    gdf["data_attivazione"] = pd.Timestamp(data_placeholder)
    gdf["data_fine"] = pd.NaT
    gdf["data_stato"] = "placeholder"

    if percorso_override is None or not percorso_override.exists():
        return gdf

    ov = pd.read_csv(percorso_override, dtype={"id_intervento": str})
    ov["data_attivazione"] = pd.to_datetime(ov["data_attivazione"], errors="raise")
    if "data_fine" in ov.columns:
        ov["data_fine"] = pd.to_datetime(ov["data_fine"], errors="raise")
    sconosciuti = set(ov["id_intervento"]) - set(gdf["id_intervento"])
    if sconosciuti:
        log.warning(
            "%d id nel CSV date non trovati tra gli interventi: %s",
            len(sconosciuti), sorted(sconosciuti)[:5],
        )
    ov = ov[ov["id_intervento"].isin(gdf["id_intervento"])]

    idx = gdf.set_index("id_intervento").index
    posizioni = pd.Series(np.arange(len(gdf)), index=idx)
    for _, riga in ov.iterrows():
        pos = posizioni[riga["id_intervento"]]
        gdf.iloc[pos, gdf.columns.get_loc("data_attivazione")] = riga["data_attivazione"]
        gdf.iloc[pos, gdf.columns.get_loc("data_stato")] = "confermata"
        if "data_fine" in ov.columns and pd.notna(riga.get("data_fine")):
            if riga["data_fine"] < riga["data_attivazione"]:
                raise ValueError(
                    f"data_fine precedente a data_attivazione per "
                    f"{riga['id_intervento']}"
                )
            gdf.iloc[pos, gdf.columns.get_loc("data_fine")] = riga["data_fine"]
        if "fase" in ov.columns and pd.notna(riga.get("fase")):
            if riga["fase"] not in FASI_VALIDE:
                raise ValueError(f"fase non valida nel CSV date: {riga['fase']}")
            gdf.iloc[pos, gdf.columns.get_loc("fase")] = riga["fase"]
    log.info("Date confermate da override: %d", len(ov))
    return gdf


def assegna_raggio_influenza(
    gdf: gpd.GeoDataFrame, raggi: dict[str, float]
) -> pd.Series:
    """Raggio d'influenza per tipo. Convenzione: 0 per geometrie areali e
    lineari (conta l'impronta/il tracciato), default per tipo o globale
    per i puntuali."""
    default_punti = float(raggi.get("default_punti", 150.0))
    e_puntuale = gdf.geometry.geom_type.isin(["Point", "MultiPoint"])
    out = pd.Series(0.0, index=gdf.index)
    for tipo in gdf["tipo"].unique():
        m = (gdf["tipo"] == tipo) & e_puntuale
        out.loc[m] = float(raggi.get(tipo, default_punti))
    return out


def riassumi_interventi(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    r: dict[str, Any] = {
        "n_interventi": int(len(gdf)),
        "n_tipi": int(gdf["tipo"].nunique()),
        "per_tipo": gdf["tipo"].value_counts().to_dict(),
        "per_fase": gdf["fase"].value_counts().to_dict(),
        "date_confermate": int((gdf["data_stato"] == "confermata").sum()),
        "geometrie_invalide": int((~gdf.geometry.is_valid).sum()),
    }
    return r


def esporta_template_date(gdf: gpd.GeoDataFrame, percorso: Path) -> None:
    """Template CSV da compilare con le date reali (anche future)."""
    tpl = gdf[["id_intervento", "tipo", "nome", "fase", "fase_orig",
               "data_stato"]].copy()
    tpl["data_attivazione"] = ""  # da compilare (inizio lavori/attivazione)
    tpl["data_fine"] = ""         # opzionale: fine lavori (esclude il cantiere)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    tpl.to_csv(percorso, index=False)
    log.info("Template date: %s (%d righe)", percorso, len(tpl))


def salva(gdf: gpd.GeoDataFrame, percorso: Path) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    if percorso.exists():
        percorso.unlink()
    # geometry_type="Unknown": il layer unificato mescola punti, linee
    # e poligoni (GPKG lo supporta).
    gdf.to_file(percorso, driver="GPKG", layer="interventi",
                geometry_type="Unknown")
    log.info("Salvato %s (%d interventi)", percorso, len(gdf))


def main(config: dict[str, Any]) -> None:
    """Unifica il database progetti nel layer normalizzato interventi."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    cfg = config["interventi"]
    crs_target = config["crs"]["metrico"]
    progetti_dir = RADICE_PROGETTO / config["paths"]["raw"]["progetti_dir"]

    pezzi: list[gpd.GeoDataFrame] = []
    for sorgente in cfg["sorgenti"]:
        gdf_s = carica_sorgente(sorgente, progetti_dir, crs_target)
        log.info("  %-40s tipo=%-22s n=%d",
                 sorgente["file"], sorgente["tipo"], len(gdf_s))
        pezzi.append(gdf_s)
    gdf = gpd.GeoDataFrame(
        pd.concat(pezzi, ignore_index=True), crs=crs_target
    )

    gdf["fase"] = normalizza_fase(gdf["fase_orig"], cfg.get("mappa_fase", {}))
    gdf = applica_date(
        gdf,
        data_placeholder=str(cfg.get("data_placeholder", "2025-01-01")),
        percorso_override=(
            RADICE_PROGETTO / cfg["date_override"]
            if cfg.get("date_override") else None
        ),
    )
    gdf["raggio_influenza_m"] = assegna_raggio_influenza(
        gdf, cfg.get("raggio_influenza_default_m", {})
    )

    if gdf["id_intervento"].duplicated().any():
        raise ValueError("id_intervento duplicati: sorgenti con lo stesso stem?")

    r = riassumi_interventi(gdf)
    log.info("Interventi unificati:")
    for k, v in r.items():
        log.info("  %s: %s", k, v)

    salva(gdf, RADICE_PROGETTO / config["paths"]["interim"]["interventi_prep"])
    esporta_template_date(
        gdf, RADICE_PROGETTO / "reports" / "interventi_da_datare.csv"
    )


if __name__ == "__main__":
    main(carica_config())
