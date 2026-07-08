"""Step 08 - Modulo Equita' distributiva (WP2 del PSS, cuore del paper).

Risponde alla domanda di ricerca: *gli interventi di sicurezza stradale e
mobilita' attiva sono distribuiti in modo equo rispetto al bisogno
(rischio + vulnerabilita' sociale), o si concentrano altrove?*

Pipeline per unita' territoriale (sezione di censimento):

1. **Vulnerabilita' sociale** (0-100): composite index degli indicatori
   di s0c (bambini, anziani, stranieri, istruzione bassa, non occupati),
   con schemi di pesi alternativi per l'analisi di sensibilita'.
2. **Rischio** (0-100): excess_EPDO dei siti di s05/s07 ripartito sulle
   sezioni (per lunghezza intersecata per i segmenti, per punto per le
   intersezioni), normalizzato per km2.
3. **Bisogno** = combinazione di vulnerabilita' e rischio (default media
   geometrica: servono entrambi per essere prioritari).
4. **Dotazione**: conteggio di interventi (s0d) la cui area di influenza
   (buffer sul raggio per i puntuali, impronta per aree/linee) interseca
   la sezione - totale e per tipologia.
5. **Statistiche di equita'** (equity_utils): Gini, concentration index
   (CI < 0 = dotazione concentrata dove il bisogno e' basso), LISA
   bivariata bisogno x dotazione, classi bivariate 3x3, equity priority
   zones.

Output:
- ``data/processed/equita.gpkg``        (layer ``sezioni``)
- ``data/processed/equita_indici.json`` (indici sintetici per tipo e
  per schema di pesi -> tabella di sensibilita' del paper)

Cautele dichiarate: MAUP (unita' = sezione; testare una seconda scala),
proxy socio-economiche al posto del reddito, dotazione = prossimita'
geometrica (non uso effettivo).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from src.config import RADICE_PROGETTO, carica_config
from src.s05_indice_composito import normalizza_robusta
from src.utils.equity_utils import (
    classifica_bivariata,
    concentration_index,
    equity_priority_zones,
    gini,
    lisa_bivariata,
)

log = logging.getLogger("s08_equita")

INDICATORI_VULNERABILITA = [
    "perc_bambini",
    "perc_anziani",
    "perc_stranieri",
    "perc_istruzione_bassa",
    "perc_non_occupati",
]


# =====================================================================
# T2.1 - Vulnerabilita' sociale
# =====================================================================


def calcola_vulnerabilita(
    sezioni: pd.DataFrame,
    pesi: dict[str, float],
    p_min: float = 1.0,
    p_max: float = 99.0,
) -> pd.Series:
    """Composite index di vulnerabilita' sociale (0-100).

    Ogni indicatore viene normalizzato 0-100 con percentili robusti
    (solo sulle sezioni abitate, per non schiacciare la scala sugli
    zeri delle sezioni vuote) e aggregato con media pesata.
    """
    somma = sum(float(v) for v in pesi.values())
    if somma <= 0:
        raise ValueError("I pesi di vulnerabilita' devono sommare > 0")
    pesi_norm = {k: float(v) / somma for k, v in pesi.items()}

    abitate = ~sezioni["pop_zero"].astype(bool)
    vuln = pd.Series(0.0, index=sezioni.index)
    for col, w in pesi_norm.items():
        if col not in sezioni.columns:
            raise ValueError(f"Indicatore di vulnerabilita' mancante: {col}")
        norm = pd.Series(0.0, index=sezioni.index)
        norm.loc[abitate] = normalizza_robusta(
            sezioni.loc[abitate, col], p_min, p_max, metodo="standard"
        )
        vuln += w * norm
    return vuln


# =====================================================================
# T2.3a - Rischio per sezione (ripartizione dell'excess EPDO)
# =====================================================================


def aggrega_rischio_sezioni(
    sezioni: gpd.GeoDataFrame,
    segmenti: gpd.GeoDataFrame,
    intersezioni: gpd.GeoDataFrame,
    colonna: str = "excess_EPDO_i",
) -> pd.Series:
    """Ripartisce l'eccesso di rischio dei siti sulle sezioni.

    - segmenti (linee): quota proporzionale alla lunghezza intersecata;
    - intersezioni (punti): alla sezione che le contiene.
    Ritorna l'eccesso totale per sezione (stesso indice di ``sezioni``).
    """
    rischio = pd.Series(0.0, index=sezioni.index)
    sez_min = sezioni[["geometry"]].copy()
    sez_min["_idx_sez"] = sezioni.index

    seg = segmenti[[colonna, "geometry"]].copy()
    seg[colonna] = seg[colonna].fillna(0.0).clip(lower=0.0)
    seg = seg[seg[colonna] > 0]
    if len(seg):
        seg["_len_tot"] = seg.geometry.length
        seg["_idx_seg"] = np.arange(len(seg))
        join = gpd.sjoin(seg, sez_min, predicate="intersects", how="inner")
        if len(join):
            # Lunghezza del pezzo di segmento dentro ciascuna sezione
            # (intersezione shapely vettoriale coppia per coppia).
            import shapely
            geom_sez = sezioni.geometry.loc[join["_idx_sez"]].to_numpy()
            pezzi = shapely.intersection(join.geometry.to_numpy(), geom_sez)
            join["_len_in"] = shapely.length(pezzi)
            join["_quota"] = np.where(
                join["_len_tot"] > 0, join["_len_in"] / join["_len_tot"], 0.0
            )
            contrib = (join[colonna] * join["_quota"]).groupby(join["_idx_sez"]).sum()
            rischio = rischio.add(contrib, fill_value=0.0)

    inter = intersezioni[[colonna, "geometry"]].copy()
    inter[colonna] = inter[colonna].fillna(0.0).clip(lower=0.0)
    inter = inter[inter[colonna] > 0]
    if len(inter):
        join = gpd.sjoin(inter, sez_min, predicate="within", how="inner")
        contrib = join.groupby("_idx_sez")[colonna].sum()
        rischio = rischio.add(contrib, fill_value=0.0)

    return rischio


# =====================================================================
# T2.2 - Dotazione di interventi per sezione
# =====================================================================


def calcola_dotazione(
    sezioni: gpd.GeoDataFrame,
    interventi: gpd.GeoDataFrame,
    tipi: list[str] | None = None,
) -> pd.DataFrame:
    """Conteggio di interventi che *servono* ciascuna sezione.

    Un intervento serve una sezione se la sua area di influenza (buffer
    ``raggio_influenza_m`` per i puntuali, impronta per linee/aree)
    interseca la sezione. Ritorna ``dot_totale`` + una colonna
    ``dot_{tipo}`` per tipologia.
    """
    interv = interventi if tipi is None else interventi[interventi["tipo"].isin(tipi)]
    interv = interv.copy()
    raggio = interv["raggio_influenza_m"].fillna(0.0).astype(float)
    interv["geometry"] = np.where(
        raggio > 0, interv.geometry.buffer(raggio), interv.geometry
    )

    sez_min = sezioni[["geometry"]].copy()
    sez_min["_idx_sez"] = sezioni.index

    out = pd.DataFrame(index=sezioni.index)
    out["dot_totale"] = 0.0
    join = gpd.sjoin(
        interv[["tipo", "geometry"]], sez_min, predicate="intersects", how="inner"
    )
    if len(join):
        tot = join.groupby("_idx_sez").size()
        out["dot_totale"] = out["dot_totale"].add(tot, fill_value=0.0)
        per_tipo = join.groupby(["_idx_sez", "tipo"]).size().unstack(fill_value=0)
        for tipo in per_tipo.columns:
            out[f"dot_{tipo}"] = 0.0
            out[f"dot_{tipo}"] = out[f"dot_{tipo}"].add(
                per_tipo[tipo], fill_value=0.0
            )
    return out.fillna(0.0)


# =====================================================================
# T2.3b - Indice di bisogno
# =====================================================================


def calcola_bisogno(
    vulnerabilita: pd.Series,
    rischio_norm: pd.Series,
    metodo: str = "geometrica",
    peso_rischio: float = 0.5,
) -> pd.Series:
    """Bisogno = combinazione di vulnerabilita' (0-100) e rischio (0-100).

    - ``geometrica`` (default): sqrt(vuln * rischio) - premia le sezioni
      dove *entrambi* sono alti (vertical equity in senso stretto);
    - ``pesata``: (1-w)*vuln + w*rischio - piu' morbida, non annulla il
      bisogno dove uno dei due e' zero.
    """
    v = vulnerabilita.clip(lower=0.0)
    r = rischio_norm.clip(lower=0.0)
    if metodo == "geometrica":
        return np.sqrt(v * r)
    if metodo == "pesata":
        w = float(peso_rischio)
        return (1.0 - w) * v + w * r
    raise ValueError(f"metodo bisogno non riconosciuto: {metodo!r}")


# =====================================================================
# Indici sintetici e sensibilita'
# =====================================================================


def calcola_indici_sintetici(
    df: pd.DataFrame,
    colonne_dotazione: list[str],
) -> dict[str, Any]:
    """Gini e concentration index sul sottoinsieme abitato, per ciascuna
    colonna di dotazione (totale e per tipo)."""
    abitate = ~df["pop_zero"].astype(bool)
    pop = df.loc[abitate, "pop_totale"].to_numpy(dtype=float)
    bisogno = df.loc[abitate, "bisogno"].to_numpy(dtype=float)

    indici: dict[str, Any] = {}
    for col in colonne_dotazione:
        dot = df.loc[abitate, col].to_numpy(dtype=float)
        indici[col] = {
            "gini": round(gini(dot, pop), 4),
            "concentration_index": round(
                concentration_index(dot, bisogno, pop), 4
            ),
            "n_interventi_coperti": float(dot.sum()),
        }
    return indici


def main(config: dict[str, Any]) -> None:  # noqa: C901
    """Esegue il modulo Equita' end-to-end."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    cfg = config.get("equita", {})
    p_min = float(config["indice_composito"]["percentile_min"])
    p_max = float(config["indice_composito"]["percentile_max"])

    # --- Input -------------------------------------------------------
    sezioni = gpd.read_file(
        RADICE_PROGETTO / config["paths"]["interim"]["censimento_prep"],
        layer="sezioni",
    )
    prio_path = RADICE_PROGETTO / config["paths"]["processed"]["priorita_finale"]
    segmenti = gpd.read_file(prio_path, layer="segmenti")
    intersezioni = gpd.read_file(prio_path, layer="intersezioni")
    interventi = gpd.read_file(
        RADICE_PROGETTO / config["paths"]["interim"]["interventi_prep"],
        layer="interventi",
    )
    log.info(
        "Input: %d sezioni, %d segmenti, %d intersezioni, %d interventi",
        len(sezioni), len(segmenti), len(intersezioni), len(interventi),
    )

    # --- 1. Vulnerabilita' (schema di pesi principale) ---------------
    pesi = cfg.get("pesi_vulnerabilita", {c: 1.0 for c in INDICATORI_VULNERABILITA})
    sezioni["vulnerabilita"] = calcola_vulnerabilita(sezioni, pesi, p_min, p_max)

    # --- 2. Rischio per sezione --------------------------------------
    log.info("Ripartizione excess_EPDO sulle sezioni...")
    excess = aggrega_rischio_sezioni(sezioni, segmenti, intersezioni)
    sezioni["excess_epdo"] = excess
    dens = excess / sezioni["area_km2"].clip(lower=1e-6)
    abitate = ~sezioni["pop_zero"].astype(bool)
    sezioni["rischio_norm"] = 0.0
    sezioni.loc[abitate, "rischio_norm"] = normalizza_robusta(
        dens.loc[abitate], p_min, p_max, metodo="zero_inflated"
    )

    # --- 3. Bisogno ----------------------------------------------------
    sezioni["bisogno"] = calcola_bisogno(
        sezioni["vulnerabilita"],
        sezioni["rischio_norm"],
        metodo=str(cfg.get("metodo_bisogno", "geometrica")),
        peso_rischio=float(cfg.get("peso_rischio", 0.5)),
    )

    # --- 4. Dotazione --------------------------------------------------
    log.info("Calcolo dotazione interventi per sezione...")
    tipi_dotazione = cfg.get("tipi_dotazione")  # None = tutti
    dot = calcola_dotazione(sezioni, interventi, tipi=tipi_dotazione)
    sezioni = sezioni.join(dot)
    col_dot = [c for c in sezioni.columns if c.startswith("dot_")]

    # --- 5. Statistiche di equita' -------------------------------------
    log.info("LISA bivariata bisogno x dotazione (solo sezioni abitate)...")
    sez_abitate = sezioni.loc[abitate].copy()
    lisa = lisa_bivariata(
        sez_abitate,
        "bisogno",
        "dot_totale",
        k_vicini=int(cfg.get("lisa_k_vicini", 8)),
        p_max=float(cfg.get("lisa_p_max", 0.05)),
        seed=int(config.get("random_seed", 42)),
    )
    for c in lisa.columns:
        sezioni[c] = lisa[c].reindex(sezioni.index)
    sezioni["lisa_sig"] = sezioni["lisa_sig"].fillna("ns")

    sezioni["classe_bivariata"] = "1-1"
    sezioni.loc[abitate, "classe_bivariata"] = classifica_bivariata(
        sezioni.loc[abitate, "bisogno"], sezioni.loc[abitate, "dot_totale"]
    )
    sezioni["equity_priority"] = False
    sezioni.loc[abitate, "equity_priority"] = equity_priority_zones(
        sezioni.loc[abitate, "bisogno"],
        sezioni.loc[abitate, "dot_totale"],
        lisa=lisa,
    )

    indici = {
        "unita_spaziale": "sezione_censimento_2021",
        "n_sezioni_abitate": int(abitate.sum()),
        "schema_pesi": "principale",
        "indici": calcola_indici_sintetici(sezioni, col_dot),
    }

    # --- Sensibilita' sui pesi di vulnerabilita' -----------------------
    sensibilita = {}
    for nome_schema, pesi_alt in (cfg.get("schemi_sensibilita") or {}).items():
        vuln_alt = calcola_vulnerabilita(sezioni, pesi_alt, p_min, p_max)
        bisogno_alt = calcola_bisogno(
            vuln_alt, sezioni["rischio_norm"],
            metodo=str(cfg.get("metodo_bisogno", "geometrica")),
            peso_rischio=float(cfg.get("peso_rischio", 0.5)),
        )
        pop = sezioni.loc[abitate, "pop_totale"].to_numpy(dtype=float)
        sensibilita[nome_schema] = {
            "concentration_index_dot_totale": round(
                concentration_index(
                    sezioni.loc[abitate, "dot_totale"].to_numpy(dtype=float),
                    bisogno_alt.loc[abitate].to_numpy(dtype=float),
                    pop,
                ),
                4,
            )
        }
    indici["sensibilita"] = sensibilita

    # --- Log e salvataggio ---------------------------------------------
    ci_tot = indici["indici"]["dot_totale"]["concentration_index"]
    log.info("RISULTATI EQUITA':")
    log.info("  Gini dot_totale: %.4f", indici["indici"]["dot_totale"]["gini"])
    log.info("  Concentration index dot_totale: %.4f  (%s)",
             ci_tot, "pro-bisogno" if ci_tot > 0 else "pro-avvantaggiati")
    log.info("  Equity priority zones: %d sezioni (pop %d)",
             int(sezioni["equity_priority"].sum()),
             int(sezioni.loc[sezioni["equity_priority"], "pop_totale"].sum()))
    log.info("  Cluster LISA HL significativi: %d",
             int((sezioni["lisa_sig"] == "HL").sum()))

    out_gpkg = RADICE_PROGETTO / config["paths"]["processed"]["equita"]
    out_gpkg.parent.mkdir(parents=True, exist_ok=True)
    if out_gpkg.exists():
        out_gpkg.unlink()
    sezioni.to_file(out_gpkg, driver="GPKG", layer="sezioni")
    log.info("Salvato %s (%d sezioni)", out_gpkg, len(sezioni))

    out_json = RADICE_PROGETTO / config["paths"]["processed"]["equita_indici"]
    with open(out_json, "w") as f:
        json.dump(indici, f, indent=2, ensure_ascii=False)
    log.info("Indici sintetici: %s", out_json)


if __name__ == "__main__":
    main(carica_config())
