"""Step 07 - High Injury Network e hotspot NKDE (Modulo A del PSS).

Estende la diagnosi del rischio da reattiva a proattiva/sistemica:

1. **High Injury Network (HIN)** - identifica la quota minima di rete
   che concentra la maggioranza dei KSI (morti + feriti; il dato non
   distingue feriti gravi da lievi). Ranking dei segmenti per KSI/km,
   opzionalmente stabilizzato con la stima Empirical Bayes (piu' robusto
   della conta grezza: gli incidenti gravi sono eventi rari).
2. **Curva di concentrazione** - % di rete vs % di KSI coperti (la figura
   "il 15% della rete contiene il 70% dei feriti gravi").
3. **NKDE (Network-constrained Kernel Density Estimation)** - densita'
   di incidenti *lungo la rete* tramite lixelizzazione dei segmenti e
   kernel 1D sulla distanza curvilinea. Approssimazione dichiarata:
   il kernel non attraversa le intersezioni (contributi solo dagli
   incidenti proiettati sullo stesso segmento). Gli incidenti abbinati
   alle intersezioni possono essere riagganciati al segmento piu'
   vicino (config ``nkde.includi_incidenti_intersezione``).

Input:  ``data/processed/priorita_finale.gpkg`` (layer segmenti e
        intersezioni, da s05) e ``data/interim/incidenti_matched.gpkg``.
Output: ``priorita_finale.gpkg`` riscritto con le colonne ``ksi_km``,
        ``is_hin``, ``rank_ksi``, ``nkde_max`` sul layer segmenti;
        ``data/processed/nkde.gpkg`` (lixel con densita');
        ``reports/hin_curva_concentrazione.csv``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, substring

from src.config import RADICE_PROGETTO, carica_config

log = logging.getLogger("s07_hin")


# =====================================================================
# T1.1 - High Injury Network
# =====================================================================


def calcola_ksi(df: pd.DataFrame, metrica: str = "ksi", usa_eb: bool = True) -> pd.Series:
    """Misura di gravita' per sito usata dal ranking HIN.

    - ``metrica="ksi"``: KSI = n_mortali + n_feriti.
    - ``metrica="epdo"``: EPDO_i (gia' calcolato in s04).

    Se ``usa_eb``, la conta osservata viene stabilizzata riscalandola con
    la stima EB della frequenza totale: ``KSI_stab = EB_i * (KSI_i / O_i)``
    (stessa costruzione di ``excess_EPDO_i`` in s04). Riduce il rumore da
    eventi rari senza cambiare la severity mix osservata del sito.
    I siti senza incidenti restano a 0.
    """
    if metrica == "epdo" and "EPDO_i" in df.columns:
        grezzo = df["EPDO_i"].fillna(0).astype(float)
    else:
        grezzo = (
            df.get("n_mortali", pd.Series(0, index=df.index)).fillna(0).astype(float)
            + df.get("n_feriti", pd.Series(0, index=df.index)).fillna(0).astype(float)
        )

    if not usa_eb or "EB_i" not in df.columns or "n_incidenti" not in df.columns:
        return grezzo

    o_i = df["n_incidenti"].fillna(0).astype(float)
    eb_i = df["EB_i"].astype(float)
    fattore = pd.Series(1.0, index=df.index)
    valido = (o_i > 0) & eb_i.notna()
    fattore.loc[valido] = eb_i.loc[valido] / o_i.loc[valido]
    return grezzo * fattore


def calcola_ksi_km(df: pd.DataFrame, ksi: pd.Series) -> pd.Series:
    """Densita' lineare di gravita': KSI (o EPDO) per km di segmento."""
    lung_km = df["lunghezza_m"].astype(float) / 1000.0
    ksi_km = pd.Series(0.0, index=df.index)
    valido = lung_km > 0
    ksi_km.loc[valido] = ksi.loc[valido] / lung_km.loc[valido]
    return ksi_km


def costruisci_hin(
    df: pd.DataFrame,
    ksi: pd.Series,
    ksi_km: pd.Series,
    soglia_copertura: float = 0.70,
) -> pd.DataFrame:
    """Costruisce il flag HIN per copertura cumulata.

    Ordina i segmenti per KSI/km decrescente e li include nella HIN
    finche' la quota cumulata di KSI raggiunge ``soglia_copertura``.
    Segmenti con KSI = 0 non entrano mai nella HIN.

    Ritorna un DataFrame (stesso indice di ``df``) con:
    - ``is_hin``   : bool
    - ``rank_ksi`` : posizione nel ranking (1 = peggiore; NaN se KSI = 0)
    """
    out = pd.DataFrame(index=df.index)
    out["is_hin"] = False
    out["rank_ksi"] = np.nan

    totale = float(ksi.sum())
    positivi = ksi_km[ksi > 0]
    if totale <= 0 or positivi.empty:
        log.warning("Nessun KSI positivo: HIN vuota.")
        return out

    ordine = positivi.sort_values(ascending=False).index
    out.loc[ordine, "rank_ksi"] = np.arange(1, len(ordine) + 1, dtype=float)

    copertura = ksi.loc[ordine].cumsum() / totale
    # Include tutti i siti fino al primo che raggiunge la soglia (compreso).
    n_hin = int(np.searchsorted(copertura.to_numpy(), soglia_copertura) + 1)
    n_hin = min(n_hin, len(ordine))
    out.loc[ordine[:n_hin], "is_hin"] = True
    return out


def curva_concentrazione(
    df: pd.DataFrame,
    ksi: pd.Series,
    ksi_km: pd.Series,
) -> pd.DataFrame:
    """Curva di concentrazione: frazione di rete (km) vs frazione di KSI.

    I segmenti sono ordinati per KSI/km decrescente: la curva risponde a
    "quanta rete serve per coprire il X% dei KSI?". E' la figura chiave
    del layer HIN nel paper.
    """
    lung_km = df["lunghezza_m"].astype(float) / 1000.0
    ordine = ksi_km.sort_values(ascending=False).index

    frac_rete = lung_km.loc[ordine].cumsum() / lung_km.sum()
    tot_ksi = float(ksi.sum())
    frac_ksi = (
        ksi.loc[ordine].cumsum() / tot_ksi
        if tot_ksi > 0
        else pd.Series(0.0, index=ordine)
    )
    return pd.DataFrame(
        {
            "frac_rete": frac_rete.to_numpy(),
            "frac_ksi": frac_ksi.to_numpy(),
            "ksi_km": ksi_km.loc[ordine].to_numpy(),
        }
    )


# =====================================================================
# T1.2 - NKDE per lixelizzazione
# =====================================================================


def _linea_unica(geom: Any) -> LineString | None:
    """Riduce la geometria a una LineString continua (merge se multi)."""
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, LineString):
        return geom
    if isinstance(geom, MultiLineString):
        merged = linemerge(geom)
        if isinstance(merged, LineString):
            return merged
        # Parti disconnesse: usa la piu' lunga (approssimazione dichiarata).
        parti = list(merged.geoms)
        return max(parti, key=lambda g: g.length)
    return None


def _kernel_quartico(u: np.ndarray) -> np.ndarray:
    """Kernel quartico (biweight): K(u) = 15/16 (1-u^2)^2 per |u|<=1."""
    k = np.zeros_like(u)
    dentro = np.abs(u) <= 1.0
    k[dentro] = 15.0 / 16.0 * (1.0 - u[dentro] ** 2) ** 2
    return k


def _pesi_epdo_incidenti(
    incidenti: pd.DataFrame, pesi_epdo: dict[str, float]
) -> np.ndarray:
    """Peso per incidente dalla gravita' (mappa i livelli di s00 sui
    pesi EPDO di config; default 1 se la colonna manca)."""
    if "gravita" not in incidenti.columns:
        return np.ones(len(incidenti))
    mappa = {
        "mortale": float(pesi_epdo.get("mortale", 1.0)),
        "ferito_lieve": float(pesi_epdo.get("feriti", 1.0)),
        "ferito_grave": float(pesi_epdo.get("feriti", 1.0)),
        "solo_danni": float(pesi_epdo.get("solo_danni", 1.0)),
    }
    return (
        incidenti["gravita"].astype(str).map(mappa).fillna(1.0).to_numpy(dtype=float)
    )


def riaggancia_incidenti_intersezione(
    incidenti: gpd.GeoDataFrame,
    segmenti: gpd.GeoDataFrame,
    raggio_snap_m: float = 50.0,
) -> gpd.GeoDataFrame:
    """Riaggancia al segmento piu' vicino gli incidenti abbinati a
    un'intersezione, cosi' che la densita' NKDE includa anche la massa
    (dominante) degli incidenti d'incrocio. Oltre ``raggio_snap_m``
    l'incidente viene scartato dalla NKDE."""
    inc = incidenti.copy()
    da_snappare = inc["tipo_sito"].astype(str) == "intersezione"
    if not da_snappare.any():
        return inc

    seg_min = segmenti[["id_segmento", "geometry"]].copy()
    snap = gpd.sjoin_nearest(
        inc.loc[da_snappare, ["geometry"]],
        seg_min,
        how="left",
        max_distance=raggio_snap_m,
        distance_col="_dist_snap",
    )
    # sjoin_nearest puo' duplicare in caso di pareggio: tieni il primo.
    snap = snap[~snap.index.duplicated(keep="first")]
    # Oltre il raggio il join lascia NaN -> l'incidente esce dalla NKDE.
    inc.loc[snap.index, "id_sito"] = snap["id_segmento"].to_numpy()
    riusciti = snap["id_segmento"].notna()
    inc.loc[snap.index[riusciti], "tipo_sito"] = "segmento"
    return inc


def calcola_nkde(
    segmenti: gpd.GeoDataFrame,
    incidenti: gpd.GeoDataFrame,
    lunghezza_lixel_m: float = 20.0,
    bandwidth_m: float = 200.0,
    pesi_incidenti: np.ndarray | None = None,
    salva_solo_positivi: bool = True,
) -> tuple[gpd.GeoDataFrame, pd.Series]:
    """NKDE 1D lungo i segmenti (lixelizzazione).

    Per ogni segmento con incidenti abbinati:
    1. proietta gli incidenti sulla linea (ascissa curvilinea);
    2. divide la linea in lixel di lunghezza ~``lunghezza_lixel_m``;
    3. densita' al centro-lixel = somma dei kernel quartici 1D
       ``K(|s_lixel - s_incidente| / h) / h`` (unita': peso per metro).

    Limite dichiarato: il kernel non attraversa le intersezioni
    (approssimazione entro-segmento della vera NKDE, cfr. Okabe &
    Sugihara). Va segnalato nel paper.

    Ritorna (lixel GeoDataFrame, nkde_max per id_segmento).
    """
    if pesi_incidenti is None:
        pesi_incidenti = np.ones(len(incidenti))
    incidenti = incidenti.assign(_peso=pesi_incidenti)

    # Solo incidenti riferiti a un segmento: gli id delle intersezioni
    # vivono in uno spazio di id diverso e non devono entrare nel groupby.
    inc_seg = incidenti[
        incidenti["tipo_sito"].astype(str) == "segmento"
    ].dropna(subset=["id_sito"])
    gruppi = inc_seg.groupby("id_sito")

    record: list[dict[str, Any]] = []
    nkde_max: dict[Any, float] = {}
    h = float(bandwidth_m)

    for _, seg in segmenti.iterrows():
        id_seg = seg["id_segmento"]
        linea = _linea_unica(seg.geometry)
        if linea is None or linea.length <= 0:
            continue

        try:
            inc_qui = gruppi.get_group(id_seg)
        except KeyError:
            if salva_solo_positivi:
                continue
            inc_qui = inc_seg.iloc[0:0]

        # Ascisse curvilinee di incidenti e centri lixel.
        s_inc = np.array([linea.project(p) for p in inc_qui.geometry])
        w_inc = inc_qui["_peso"].to_numpy(dtype=float)

        n_lixel = max(1, int(np.ceil(linea.length / lunghezza_lixel_m)))
        bordi = np.linspace(0.0, linea.length, n_lixel + 1)
        centri = 0.5 * (bordi[:-1] + bordi[1:])

        if len(s_inc):
            u = (centri[:, None] - s_inc[None, :]) / h
            densita = (_kernel_quartico(u) / h * w_inc[None, :]).sum(axis=1)
        else:
            densita = np.zeros(n_lixel)

        nkde_max[id_seg] = float(densita.max()) if n_lixel else 0.0

        for i in range(n_lixel):
            if salva_solo_positivi and densita[i] <= 0:
                continue
            record.append(
                {
                    "id_segmento": id_seg,
                    "offset_m": float(centri[i]),
                    "nkde": float(densita[i]),
                    "geometry": substring(linea, bordi[i], bordi[i + 1]),
                }
            )

    if record:
        gdf_lixel = gpd.GeoDataFrame(record, crs=segmenti.crs, geometry="geometry")
    else:
        gdf_lixel = gpd.GeoDataFrame(
            {"id_segmento": [], "offset_m": [], "nkde": []},
            geometry=gpd.GeoSeries([], crs=segmenti.crs),
        )
    serie_max = pd.Series(nkde_max, name="nkde_max")
    serie_max.index.name = "id_segmento"
    return gdf_lixel, serie_max


# =====================================================================
# Riassunto, salvataggio, pipeline
# =====================================================================


def riassumi_hin(
    df: pd.DataFrame, ksi: pd.Series, curva: pd.DataFrame
) -> dict[str, Any]:
    """Statistiche di sintesi del layer HIN."""
    hin = df["is_hin"] == True  # noqa: E712
    lung_km = df["lunghezza_m"].astype(float) / 1000.0
    tot_ksi = float(ksi.sum())
    r: dict[str, Any] = {
        "n_segmenti": int(len(df)),
        "n_segmenti_hin": int(hin.sum()),
        "km_rete": round(float(lung_km.sum()), 1),
        "km_hin": round(float(lung_km[hin].sum()), 1),
        "pct_rete_hin": round(100.0 * float(lung_km[hin].sum()) / float(lung_km.sum()), 1)
        if lung_km.sum() > 0
        else 0.0,
        "pct_ksi_hin": round(100.0 * float(ksi[hin].sum()) / tot_ksi, 1)
        if tot_ksi > 0
        else 0.0,
    }
    return r


def main(config: dict[str, Any]) -> None:
    """Calcola HIN, curva di concentrazione e NKDE."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    cfg_hin = config.get("hin", {})
    cfg_nkde = config.get("nkde", {})

    prio_path = RADICE_PROGETTO / config["paths"]["processed"]["priorita_finale"]
    log.info("Caricamento priorita' finale da %s", prio_path)
    gdf_seg = gpd.read_file(prio_path, layer="segmenti")
    gdf_int = gpd.read_file(prio_path, layer="intersezioni")

    inc_path = RADICE_PROGETTO / config["paths"]["interim"]["incidenti_matched"]
    log.info("Caricamento incidenti matched da %s", inc_path)
    gdf_inc = gpd.read_file(inc_path, layer="incidenti_matched")
    if gdf_inc.crs != gdf_seg.crs:
        gdf_inc = gdf_inc.to_crs(gdf_seg.crs)

    # Adattatore di schema: s02 salva ``match_type``/``id_match``; le
    # funzioni di questo modulo lavorano con ``tipo_sito``/``id_sito``.
    # ``segmento_toponimo`` e' a tutti gli effetti un match su segmento.
    if "tipo_sito" not in gdf_inc.columns and "match_type" in gdf_inc.columns:
        gdf_inc["tipo_sito"] = gdf_inc["match_type"].replace(
            {"segmento_toponimo": "segmento"}
        )
        gdf_inc["id_sito"] = gdf_inc["id_match"]

    # Coerenza col periodo delle SPF: la NKDE usa gli stessi anni con cui
    # sono stati contati gli incidenti in s03 (altrimenti mescolerebbe
    # epoche diverse nella densita').
    anni_spf = config.get("spf", {}).get("anni_incidenti")
    if anni_spf and "anno" in gdf_inc.columns:
        n_prima = len(gdf_inc)
        gdf_inc = gdf_inc[gdf_inc["anno"].isin([int(a) for a in anni_spf])].copy()
        log.info(
            "Filtro anni SPF %s: %d -> %d incidenti", anni_spf, n_prima, len(gdf_inc)
        )

    # --- HIN --------------------------------------------------------
    metrica = str(cfg_hin.get("metrica", "ksi"))
    usa_eb = bool(cfg_hin.get("usa_eb", True))
    soglia = float(cfg_hin.get("soglia_copertura", 0.70))

    ksi = calcola_ksi(gdf_seg, metrica=metrica, usa_eb=usa_eb)
    ksi_km = calcola_ksi_km(gdf_seg, ksi)
    hin = costruisci_hin(gdf_seg, ksi, ksi_km, soglia_copertura=soglia)
    gdf_seg["ksi_km"] = ksi_km
    gdf_seg["is_hin"] = hin["is_hin"]
    gdf_seg["rank_ksi"] = hin["rank_ksi"]

    curva = curva_concentrazione(gdf_seg, ksi, ksi_km)
    curva_path = RADICE_PROGETTO / "reports" / "hin_curva_concentrazione.csv"
    curva_path.parent.mkdir(parents=True, exist_ok=True)
    curva.to_csv(curva_path, index=False)
    log.info("Curva di concentrazione: %s", curva_path)

    r = riassumi_hin(gdf_seg, ksi, curva)
    log.info("HIN (metrica=%s, usa_eb=%s, soglia=%.0f%%):", metrica, usa_eb, 100 * soglia)
    for k, v in r.items():
        log.info("  %s: %s", k, v)

    # --- NKDE -------------------------------------------------------
    if bool(cfg_nkde.get("includi_incidenti_intersezione", True)):
        raggio_snap = float(cfg_nkde.get("raggio_snap_intersezioni_m", 50.0))
        gdf_inc = riaggancia_incidenti_intersezione(gdf_inc, gdf_seg, raggio_snap)

    peso_tipo = str(cfg_nkde.get("peso", "epdo"))
    pesi = (
        _pesi_epdo_incidenti(gdf_inc, config.get("epdo", {}).get("pesi", {}))
        if peso_tipo == "epdo"
        else None
    )
    log.info("Calcolo NKDE (lixel=%sm, bandwidth=%sm, peso=%s)...",
             cfg_nkde.get("lunghezza_lixel_m", 20), cfg_nkde.get("bandwidth_m", 200), peso_tipo)
    gdf_lixel, nkde_max = calcola_nkde(
        gdf_seg,
        gdf_inc,
        lunghezza_lixel_m=float(cfg_nkde.get("lunghezza_lixel_m", 20.0)),
        bandwidth_m=float(cfg_nkde.get("bandwidth_m", 200.0)),
        pesi_incidenti=pesi,
        salva_solo_positivi=bool(cfg_nkde.get("salva_solo_positivi", True)),
    )
    log.info("NKDE: %d lixel positivi su %d segmenti", len(gdf_lixel), len(nkde_max))

    gdf_seg = gdf_seg.merge(nkde_max, on="id_segmento", how="left")
    gdf_seg["nkde_max"] = gdf_seg["nkde_max"].fillna(0.0)

    nkde_path = RADICE_PROGETTO / config["paths"]["processed"].get(
        "nkde", "data/processed/nkde.gpkg"
    )
    nkde_path.parent.mkdir(parents=True, exist_ok=True)
    if nkde_path.exists():
        nkde_path.unlink()
    if len(gdf_lixel):
        gdf_lixel.to_file(nkde_path, driver="GPKG", layer="nkde")
        log.info("NKDE lixel: %s (%d record)", nkde_path, len(gdf_lixel))

    # --- Riscrittura priorita_finale con le nuove colonne ------------
    if prio_path.exists():
        prio_path.unlink()
    gdf_seg.to_file(prio_path, driver="GPKG", layer="segmenti")
    gdf_int.to_file(prio_path, driver="GPKG", layer="intersezioni")
    log.info("Aggiornato %s (colonne ksi_km, is_hin, rank_ksi, nkde_max)", prio_path)


if __name__ == "__main__":
    main(carica_config())
