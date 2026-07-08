"""Step 09 - Ottimizzazione della localizzazione degli interventi (WP3).

Rende lo strumento *prescrittivo*: dato un budget di p interventi e un
raggio d'influenza, propone dove collocarli massimizzando una domanda
che bilancia **rischio** ed **equita'**:

    d_i(w) = (1 - w) * rischio_norm_i + w * vulnerabilita_i     w in [0, 1]

- ``rischio_norm``: excess EPDO per km2 della sezione (0-100, da s08);
- ``vulnerabilita``: vulnerabilita' *sociale* della sezione (0-100, da
  s08) - NON il "bisogno" composito, che contiene gia' il rischio e
  renderebbe i due obiettivi correlati per costruzione (frontiera
  piatta, verificato empiricamente su Roma);
- ``w``: il peso dell'equita' - lo slider della tab "Scenari".

Formulazione MCLP (Church & ReVelle 1974) su:
- **domanda**: le sezioni di censimento abitate con domanda > 0
  (punto rappresentativo);
- **candidati**: unione di (a) i primi ``n_candidati_rischio`` siti per
  excess_EPDO e (b) i primi ``n_candidati_equita`` siti per frequenza
  attesa EB dentro le equity priority zones - senza (b) le aree
  vulnerabili senza storico incidenti sarebbero irraggiungibili anche
  a w=1 (un intervento deve comunque stare sulla rete).

La **frontiera di Pareto** viene pre-calcolata qui (default greedy,
garanzia 1-1/e e di fatto quasi-ottimo su istanze spaziali; solver
esatto CBC disponibile via config) cosi' la dashboard non risolve mai
nulla nei callback: lo slider seleziona uno scenario pre-calcolato.

Output:
- ``data/processed/scenari.parquet``      (siti scelti per ogni w)
- ``data/processed/scenari_indici.json``  (punti della frontiera)
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
from src.utils.optim_utils import costruisci_copertura, risolvi_mclp

log = logging.getLogger("s09_ottimizzazione")


def costruisci_domanda(
    sezioni: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Punti di domanda: sezioni abitate con rischio o vulnerabilita'
    positivi.

    Ritorna un GeoDataFrame (punto rappresentativo) con le colonne
    ``rischio_norm``, ``vulnerabilita``, ``equity_priority``,
    ``pop_totale``.
    """
    ab = ~sezioni["pop_zero"].astype(bool)
    con_domanda = ab & (
        (sezioni["rischio_norm"] > 0) | (sezioni["vulnerabilita"] > 0)
    )
    dom = sezioni.loc[
        con_domanda,
        ["SEZ21_ID", "rischio_norm", "vulnerabilita", "equity_priority",
         "pop_totale", "geometry"],
    ].copy()
    dom["equity_priority"] = dom["equity_priority"].fillna(False).astype(bool)
    dom["geometry"] = dom.geometry.representative_point()
    return dom.reset_index(drop=True)


def costruisci_candidati(
    segmenti: gpd.GeoDataFrame,
    intersezioni: gpd.GeoDataFrame,
    sezioni: gpd.GeoDataFrame | None = None,
    n_candidati_rischio: int = 1500,
    n_candidati_equita: int = 1500,
) -> gpd.GeoDataFrame:
    """Siti candidati (geometria ridotta al punto rappresentativo).

    Unione di due insiemi (dedup su tipo+id):
    - **rischio**: siti con eccesso EB positivo, primi
      ``n_candidati_rischio`` per excess_EPDO_i;
    - **equita'**: siti dentro le equity priority zones (se ``sezioni``
      e' fornito), primi ``n_candidati_equita`` per frequenza attesa
      EB_i - candidati proattivi dove il rischio storico puo' mancare.
    """
    pezzi = []
    for gdf, tipo, col_id in (
        (segmenti, "segmento", "id_segmento"),
        (intersezioni, "intersezione", "id_nodo"),
    ):
        d = gdf[[col_id, "toponimo", "excess_EPDO_i", "EB_i", "geometry"]].copy()
        d["tipo_sito"] = tipo
        d = d.rename(columns={col_id: "id_sito"})
        pezzi.append(d)
    siti = gpd.GeoDataFrame(
        pd.concat(pezzi, ignore_index=True), geometry="geometry", crs=segmenti.crs
    )
    siti["geometry"] = siti.geometry.representative_point()

    cand_rischio = siti[siti["excess_EPDO_i"].fillna(0) > 0].nlargest(
        int(n_candidati_rischio), "excess_EPDO_i"
    )

    cand_equita = siti.iloc[0:0]
    if sezioni is not None and "equity_priority" in sezioni.columns:
        zone = sezioni.loc[
            sezioni["equity_priority"].fillna(False).astype(bool), ["geometry"]
        ]
        if len(zone):
            dentro = gpd.sjoin(
                siti, zone, predicate="within", how="inner"
            ).drop(columns="index_right")
            dentro = dentro[~dentro.index.duplicated(keep="first")]
            cand_equita = dentro[dentro["EB_i"].fillna(0) > 0].nlargest(
                int(n_candidati_equita), "EB_i"
            )

    cand = pd.concat([cand_rischio, cand_equita], ignore_index=False)
    cand = cand[~cand.duplicated(subset=["tipo_sito", "id_sito"], keep="first")]
    return gpd.GeoDataFrame(cand.reset_index(drop=True), crs=segmenti.crs)


def domanda_pesata(
    dom: pd.DataFrame, peso_equita: float
) -> np.ndarray:
    """d_i(w) = (1-w) * rischio_norm + w * vulnerabilita."""
    w = float(peso_equita)
    if not 0.0 <= w <= 1.0:
        raise ValueError("peso_equita deve stare in [0, 1]")
    return (
        (1.0 - w) * dom["rischio_norm"].to_numpy(dtype=float)
        + w * dom["vulnerabilita"].to_numpy(dtype=float)
    )


def frontiera_pareto(
    dom: gpd.GeoDataFrame,
    cand: gpd.GeoDataFrame,
    copertura,
    p: int,
    n_punti: int = 11,
    metodo: str = "greedy",
    timeout_s: int = 120,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Risolve l'MCLP per w in [0, 1] e misura i trade-off.

    Per ogni scenario: % di rischio totale coperto e % di bisogno totale
    coperto (le due dimensioni della frontiera), piu' i siti scelti.
    """
    rischio = dom["rischio_norm"].to_numpy(dtype=float)
    vuln = dom["vulnerabilita"].to_numpy(dtype=float)
    pop = dom["pop_totale"].to_numpy(dtype=float)
    prio = dom["equity_priority"].to_numpy(dtype=bool)
    # Le due % misurano le stesse quantita' che entrano nella domanda
    # d_i(w) (coerenza con l'obiettivo ottimizzato); la metrica
    # "umana" e' pct_pop_priority_coperta: quante persone delle equity
    # priority zones sono servite.
    tot_rischio = float(rischio.sum()) or 1.0
    tot_vuln = float(vuln.sum()) or 1.0
    tot_pop_prio = float(pop[prio].sum()) or 1.0

    righe_scelte: list[pd.DataFrame] = []
    frontiera: list[dict[str, Any]] = []

    for w in np.linspace(0.0, 1.0, int(n_punti)):
        w = round(float(w), 3)
        ris = risolvi_mclp(
            domanda_pesata(dom, w), copertura, p,
            metodo=metodo, timeout_s=timeout_s,
        )
        coperto = ris["coperto"]
        punto = {
            "peso_equita": w,
            "pct_rischio_coperto": round(
                100.0 * float(rischio[coperto].sum()) / tot_rischio, 2),
            "pct_vulnerabilita_coperta": round(
                100.0 * float(vuln[coperto].sum()) / tot_vuln, 2),
            "pct_pop_priority_coperta": round(
                100.0 * float(pop[coperto & prio].sum()) / tot_pop_prio, 2),
            "pop_coperta": int(pop[coperto].sum()),
            "n_scelti": len(ris["scelti"]),
            "metodo": ris["metodo"],
            "ottimo_garantito": bool(ris["ottimo_garantito"]),
        }
        frontiera.append(punto)
        log.info(
            "  w=%.1f -> rischio %.1f%%, vulnerabilita' %.1f%%, pop priority %.1f%%",
            w, punto["pct_rischio_coperto"],
            punto["pct_vulnerabilita_coperta"],
            punto["pct_pop_priority_coperta"],
        )

        sel = cand.iloc[ris["scelti"]].copy()
        sel["peso_equita"] = w
        sel["ordine"] = np.arange(1, len(sel) + 1)
        righe_scelte.append(sel)

    scelte = pd.concat(righe_scelte, ignore_index=True)
    return scelte, frontiera


def main(config: dict[str, Any]) -> None:
    """Pre-calcola scenari e frontiera per la tab Scenari."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    cfg = config.get("ottimizzazione", {})
    p = int(cfg.get("budget_default", 20))
    raggio = float(cfg.get("raggio_copertura_m", 500))
    n_cand_r = int(cfg.get("n_candidati_rischio", 1500))
    n_cand_e = int(cfg.get("n_candidati_equita", 1500))
    n_punti = int(cfg.get("n_punti_frontiera", 11))
    metodo = str(cfg.get("metodo", "greedy"))
    timeout_s = int(cfg.get("timeout_s", 120))

    sezioni = gpd.read_file(
        RADICE_PROGETTO / config["paths"]["processed"]["equita"], layer="sezioni"
    )
    prio = RADICE_PROGETTO / config["paths"]["processed"]["priorita_finale"]
    segmenti = gpd.read_file(prio, layer="segmenti")
    intersezioni = gpd.read_file(prio, layer="intersezioni")

    dom = costruisci_domanda(sezioni)
    cand = costruisci_candidati(
        segmenti, intersezioni, sezioni=sezioni,
        n_candidati_rischio=n_cand_r, n_candidati_equita=n_cand_e,
    )
    log.info(
        "MCLP: %d punti di domanda, %d candidati, budget=%d, raggio=%.0fm, metodo=%s",
        len(dom), len(cand), p, raggio, metodo,
    )

    xy_dom = np.column_stack([dom.geometry.x, dom.geometry.y])
    xy_cand = np.column_stack([cand.geometry.x, cand.geometry.y])
    copertura = costruisci_copertura(xy_cand, xy_dom, raggio)
    log.info("Matrice di copertura: %d coppie entro il raggio", copertura.nnz)

    scelte, frontiera = frontiera_pareto(
        dom, cand, copertura, p,
        n_punti=n_punti, metodo=metodo, timeout_s=timeout_s,
    )

    # Coordinate WGS84 per la dashboard.
    scelte_wgs = gpd.GeoDataFrame(
        scelte, geometry="geometry", crs=cand.crs
    ).to_crs("EPSG:4326")
    scelte_wgs["lon"] = scelte_wgs.geometry.x
    scelte_wgs["lat"] = scelte_wgs.geometry.y

    out_parquet = RADICE_PROGETTO / config["paths"]["processed"]["scenari"]
    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(scelte_wgs.drop(columns="geometry")).to_parquet(
        out_parquet, index=False
    )
    log.info("Scenari: %s (%d righe)", out_parquet, len(scelte_wgs))

    out_json = RADICE_PROGETTO / config["paths"]["processed"]["scenari_indici"]
    indici = {
        "budget": p,
        "raggio_copertura_m": raggio,
        "n_candidati": len(cand),
        "n_punti_domanda": len(dom),
        "metodo": metodo,
        "frontiera": frontiera,
    }
    with open(out_json, "w") as f:
        json.dump(indici, f, indent=2, ensure_ascii=False)
    log.info("Frontiera: %s", out_json)


if __name__ == "__main__":
    main(carica_config())
