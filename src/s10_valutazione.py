"""Step 10 - Valutazione before-after degli interventi (WP4 del PSS).

Chiude il ciclo delle politiche: per ogni intervento del database (s0d)
stima l'effetto sull'incidentalita' col metodo **Empirical Bayes
before-after** (Hauer 1997, standard dello Highway Safety Manual),
riusando le SPF gia' calibrate in s03. Il confronto naive prima/dopo e'
distorto da regression-to-the-mean e trend: l'EB costruisce il
controfattuale ("quanti incidenti ci sarebbero stati SENZA intervento").

Per ogni sito trattato s e periodo prima/dopo:

    w_s        = 1 / (1 + k * E_pre_s)
    EB_pre_s   = w_s * E_pre_s + (1 - w_s) * O_pre_s
    pi_s       = EB_pre_s * (E_post_s / E_pre_s)     # atteso "dopo" senza intervento
    Var(pi_s)  = (E_post_s / E_pre_s)^2 * EB_pre_s * (1 - w_s)

Aggregando sui siti dell'intervento (somme di pi e varianze):

    theta      = (O_post / pi) / (1 + Var(pi)/pi^2)  # indice di efficacia (CMF)
    Var(theta) = theta^2 * (1/O_post + Var(pi)/pi^2) / (1 + Var(pi)/pi^2)^2

theta < 1 = riduzione attribuibile all'intervento (es. 0.75 = -25%).

**Progettato per il database in divenire**: con le date segnaposto
(2025-01-01) il periodo "dopo" non ha ancora abbastanza dati e gli
interventi risultano ``valutabile = False`` con il motivo esplicito;
quando le date reali arrivano nel CSV di override (s0d), lo stesso run
li valuta automaticamente. Nessuna modifica al codice richiesta.

Limiti dichiarati (per il paper): E annuo assunto costante nel tempo
(le SPF sono calibrate su un periodo fisso, senza serie di traffico
annuali); gruppo di controllo e ITS sono le estensioni previste appena
esiste >=1 caso reale con data confermata.

Output: ``data/processed/valutazioni.parquet``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from src.config import RADICE_PROGETTO, carica_config

log = logging.getLogger("s10_valutazione")

Z95 = 1.959964


# =====================================================================
# T4.1 - Associazione interventi -> siti trattati e finestre temporali
# =====================================================================


def siti_trattati(
    interventi: gpd.GeoDataFrame,
    segmenti: gpd.GeoDataFrame,
    intersezioni: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Coppie (id_intervento, tipo_sito, id_sito) dei siti nella zona di
    influenza di ciascun intervento.

    Zona di influenza: buffer di ``raggio_influenza_m`` per i puntuali
    (raggio > 0), impronta della geometria per aree/linee (raggio 0).
    """
    area = interventi[["id_intervento", "geometry"]].copy()
    raggio = interventi["raggio_influenza_m"].fillna(0.0).astype(float)
    area["geometry"] = np.where(
        raggio > 0, interventi.geometry.buffer(raggio), interventi.geometry
    )

    coppie = []
    for gdf, tipo, col_id in (
        (segmenti, "segmento", "id_segmento"),
        (intersezioni, "intersezione", "id_nodo"),
    ):
        siti = gdf[[col_id, "geometry"]].copy()
        join = gpd.sjoin(siti, area, predicate="intersects", how="inner")
        out = join[[col_id, "id_intervento"]].rename(columns={col_id: "id_sito"})
        out["tipo_sito"] = tipo
        coppie.append(out)
    return pd.concat(coppie, ignore_index=True).drop_duplicates()


def finestre_temporali(
    data_attivazione: pd.Timestamp,
    data_min: pd.Timestamp,
    data_max: pd.Timestamp,
    n_anni_pre: float,
    n_anni_post: float,
) -> dict[str, Any]:
    """Finestre prima/dopo troncate sulla disponibilita' dei dati.

    - prima: [attivazione - n_anni_pre, attivazione)
    - dopo:  [attivazione, attivazione + n_anni_post)
    Il periodo lavori (data_fine) andra' escluso quando disponibile.
    Ritorna anche gli anni *effettivi* (dopo il troncamento), usati per
    scalare le predizioni SPF.
    """
    att = pd.Timestamp(data_attivazione)
    pre_inizio = max(att - pd.DateOffset(years=int(n_anni_pre)), data_min)
    pre_fine = att
    post_inizio = att
    post_fine = min(att + pd.DateOffset(years=int(n_anni_post)), data_max)

    anni_pre = max((pre_fine - pre_inizio).days, 0) / 365.25
    anni_post = max((post_fine - post_inizio).days, 0) / 365.25
    return {
        "pre_inizio": pre_inizio, "pre_fine": pre_fine,
        "post_inizio": post_inizio, "post_fine": post_fine,
        "anni_pre_eff": round(anni_pre, 3),
        "anni_post_eff": round(anni_post, 3),
    }


# =====================================================================
# T4.2 - Empirical Bayes before-after (Hauer 1997)
# =====================================================================


def eb_before_after(
    o_pre: np.ndarray,
    o_post_tot: float,
    e_pre: np.ndarray,
    e_post: np.ndarray,
    k: np.ndarray,
) -> dict[str, float]:
    """Stima l'indice di efficacia theta (CMF) su un gruppo di siti.

    Input per-sito (array allineati): osservati e attesi SPF nel periodo
    prima, attesi nel dopo, sovradispersione k. ``o_post_tot`` e' il
    totale osservato nel dopo su tutti i siti.
    """
    o_pre = np.asarray(o_pre, dtype=float)
    e_pre = np.asarray(e_pre, dtype=float)
    e_post = np.asarray(e_post, dtype=float)
    k = np.asarray(k, dtype=float)

    valido = np.isfinite(e_pre) & (e_pre > 0) & np.isfinite(k) & (k > 0)
    if not valido.any():
        return {"theta": np.nan, "var_theta": np.nan,
                "pi": np.nan, "ic_low": np.nan, "ic_high": np.nan,
                "n_siti_validi": 0}

    o, ep, eo, kk = o_pre[valido], e_pre[valido], e_post[valido], k[valido]
    w = 1.0 / (1.0 + kk * ep)
    eb_pre = w * ep + (1.0 - w) * o
    ratio = eo / ep
    pi_s = eb_pre * ratio
    var_pi_s = ratio ** 2 * eb_pre * (1.0 - w)

    pi = float(pi_s.sum())
    var_pi = float(var_pi_s.sum())
    if pi <= 0:
        return {"theta": np.nan, "var_theta": np.nan, "pi": pi,
                "ic_low": np.nan, "ic_high": np.nan,
                "n_siti_validi": int(valido.sum())}

    correzione = 1.0 + var_pi / pi ** 2
    theta = (float(o_post_tot) / pi) / correzione

    if o_post_tot > 0:
        var_theta = (
            theta ** 2
            * (1.0 / float(o_post_tot) + var_pi / pi ** 2)
            / correzione ** 2
        )
        se = np.sqrt(var_theta)
        ic_low, ic_high = max(theta - Z95 * se, 0.0), theta + Z95 * se
    else:
        # Zero osservati nel dopo: theta = 0, limite superiore ~ Poisson
        # (3 eventi equivalenti sull'atteso corretto).
        var_theta = np.nan
        ic_low, ic_high = 0.0, 3.0 / pi / correzione

    return {
        "theta": float(theta), "var_theta": float(var_theta),
        "pi": pi, "ic_low": float(ic_low), "ic_high": float(ic_high),
        "n_siti_validi": int(valido.sum()),
    }


# =====================================================================
# Valutazione per intervento
# =====================================================================


def _conteggi_finestra(
    incidenti: pd.DataFrame,
    chiavi: pd.DataFrame,
    inizio: pd.Timestamp,
    fine: pd.Timestamp,
) -> pd.Series:
    """Conteggio incidenti per (tipo_sito, id_sito) nella finestra
    [inizio, fine), limitato alle coppie in ``chiavi``."""
    m = (incidenti["data_ora"] >= inizio) & (incidenti["data_ora"] < fine)
    sub = incidenti.loc[m]
    conte = sub.groupby(["tipo_sito", "id_sito"]).size()
    idx = pd.MultiIndex.from_frame(chiavi[["tipo_sito", "id_sito"]])
    return conte.reindex(idx, fill_value=0).to_numpy(dtype=float)


def valuta_interventi(
    interventi: gpd.GeoDataFrame,
    coppie: pd.DataFrame,
    incidenti: pd.DataFrame,
    siti_attr: pd.DataFrame,
    n_anni_spf: float,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Applica l'EB before-after a ogni intervento.

    ``siti_attr``: (tipo_sito, id_sito) -> E_i (sul periodo SPF), k_spf.
    ``cfg``: n_anni_pre, n_anni_post, mesi_minimi_pre, mesi_minimi_post.
    """
    data_min = incidenti["data_ora"].min()
    # +1 giorno: le finestre sono half-open [inizio, fine) e senza questo
    # margine l'ultimo incidente del dataset resterebbe sempre escluso.
    data_max = incidenti["data_ora"].max() + pd.Timedelta(days=1)
    log.info("Dati incidenti disponibili: %s -> %s",
             data_min.date(), incidenti["data_ora"].max().date())

    attr = siti_attr.set_index(["tipo_sito", "id_sito"])
    righe: list[dict[str, Any]] = []

    for _, interv in interventi.iterrows():
        riga: dict[str, Any] = {
            "id_intervento": interv["id_intervento"],
            "tipo": interv["tipo"],
            "nome": interv.get("nome"),
            "fase": interv.get("fase"),
            "data_attivazione": interv["data_attivazione"],
            "data_stato": interv.get("data_stato", "placeholder"),
            "valutabile": False,
            "motivo": None,
        }

        mie = coppie[coppie["id_intervento"] == interv["id_intervento"]]
        riga["n_siti"] = int(len(mie))
        if mie.empty:
            riga["motivo"] = "nessun_sito_trattato"
            righe.append(riga)
            continue

        fin = finestre_temporali(
            interv["data_attivazione"], data_min, data_max,
            cfg["n_anni_pre"], cfg["n_anni_post"],
        )
        riga.update({k: fin[k] for k in ("anni_pre_eff", "anni_post_eff")})

        if fin["anni_pre_eff"] * 12 < float(cfg["mesi_minimi_pre"]):
            riga["motivo"] = "pre_insufficiente"
            righe.append(riga)
            continue
        if fin["anni_post_eff"] * 12 < float(cfg["mesi_minimi_post"]):
            riga["motivo"] = "post_insufficiente"
            righe.append(riga)
            continue

        idx = pd.MultiIndex.from_frame(mie[["tipo_sito", "id_sito"]])
        e_spf = attr["E_i"].reindex(idx).to_numpy(dtype=float)
        k_spf = attr["k_spf"].reindex(idx).to_numpy(dtype=float)
        e_annuo = e_spf / float(n_anni_spf)

        o_pre = _conteggi_finestra(
            incidenti, mie, fin["pre_inizio"], fin["pre_fine"])
        o_post = _conteggi_finestra(
            incidenti, mie, fin["post_inizio"], fin["post_fine"])

        ris = eb_before_after(
            o_pre=o_pre,
            o_post_tot=float(o_post.sum()),
            e_pre=e_annuo * fin["anni_pre_eff"],
            e_post=e_annuo * fin["anni_post_eff"],
            k=k_spf,
        )
        riga.update(ris)
        riga["O_pre"] = float(o_pre.sum())
        riga["O_post"] = float(o_post.sum())
        if ris["n_siti_validi"] == 0:
            riga["motivo"] = "spf_mancante"
        else:
            riga["valutabile"] = True
        righe.append(riga)

    return pd.DataFrame(righe)


def riassumi_valutazioni(df: pd.DataFrame) -> dict[str, Any]:
    r: dict[str, Any] = {
        "n_interventi": int(len(df)),
        "n_valutabili": int(df["valutabile"].sum()),
        "motivi_non_valutabili": (
            df.loc[~df["valutabile"], "motivo"].value_counts().to_dict()
        ),
    }
    val = df[df["valutabile"]]
    if len(val):
        r["theta_mediano"] = round(float(val["theta"].median()), 3)
        r["per_tipo"] = {
            t: round(float(g["theta"].median()), 3)
            for t, g in val.groupby("tipo")
        }
    return r


def main(config: dict[str, Any]) -> None:
    """Valuta tutti gli interventi del database (quelli valutabili)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    cfg = config.get("before_after", {})
    cfg = {
        "n_anni_pre": float(cfg.get("n_anni_pre", 3)),
        "n_anni_post": float(cfg.get("n_anni_post", 2)),
        "mesi_minimi_pre": float(cfg.get("mesi_minimi_pre", 24)),
        "mesi_minimi_post": float(cfg.get("mesi_minimi_post", 12)),
    }

    interventi = gpd.read_file(
        RADICE_PROGETTO / config["paths"]["interim"]["interventi_prep"],
        layer="interventi",
    )
    interventi["data_attivazione"] = pd.to_datetime(interventi["data_attivazione"])

    prio = RADICE_PROGETTO / config["paths"]["processed"]["priorita_finale"]
    segmenti = gpd.read_file(prio, layer="segmenti")
    intersezioni = gpd.read_file(prio, layer="intersezioni")

    incidenti = gpd.read_file(
        RADICE_PROGETTO / config["paths"]["interim"]["incidenti_matched"],
        layer="incidenti_matched",
    )
    # Adattatore di schema (come in s07): match_type/id_match -> interno.
    if "tipo_sito" not in incidenti.columns and "match_type" in incidenti.columns:
        incidenti["tipo_sito"] = incidenti["match_type"].replace(
            {"segmento_toponimo": "segmento"}
        )
        incidenti["id_sito"] = incidenti["id_match"]
    incidenti = incidenti.dropna(subset=["id_sito", "data_ora"])
    incidenti = incidenti[incidenti["tipo_sito"].isin(["segmento", "intersezione"])]
    incidenti["data_ora"] = pd.to_datetime(incidenti["data_ora"])

    log.info("Associazione interventi -> siti trattati...")
    coppie = siti_trattati(interventi, segmenti, intersezioni)
    log.info("Coppie intervento-sito: %d", len(coppie))

    # Attributi SPF dei siti.
    attr = pd.concat([
        segmenti[["id_segmento", "E_i", "k_spf"]]
        .rename(columns={"id_segmento": "id_sito"}).assign(tipo_sito="segmento"),
        intersezioni[["id_nodo", "E_i", "k_spf"]]
        .rename(columns={"id_nodo": "id_sito"}).assign(tipo_sito="intersezione"),
    ], ignore_index=True)

    anni_spf = config.get("spf", {}).get("anni_incidenti") or []
    n_anni_spf = float(len(anni_spf)) if anni_spf else 1.0
    log.info("Periodo SPF: %s anni (%s)", n_anni_spf, anni_spf)

    valutazioni = valuta_interventi(
        interventi, coppie, incidenti, attr, n_anni_spf, cfg
    )

    # Coordinate WGS84 (punto rappresentativo) per la mappa della tab
    # Valutazione.
    punti = interventi.set_index("id_intervento").geometry.representative_point()
    punti_wgs = gpd.GeoSeries(punti, crs=interventi.crs).to_crs("EPSG:4326")
    valutazioni["lon"] = valutazioni["id_intervento"].map(punti_wgs.x)
    valutazioni["lat"] = valutazioni["id_intervento"].map(punti_wgs.y)

    r = riassumi_valutazioni(valutazioni)
    log.info("Valutazioni before-after:")
    for k, v in r.items():
        log.info("  %s: %s", k, v)

    out = RADICE_PROGETTO / config["paths"]["processed"]["valutazioni"]
    out.parent.mkdir(parents=True, exist_ok=True)
    valutazioni.to_parquet(out, index=False)
    log.info("Salvato %s (%d interventi)", out, len(valutazioni))


if __name__ == "__main__":
    main(carica_config())
