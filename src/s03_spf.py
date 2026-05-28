"""Step 03 - Calibrazione delle Safety Performance Functions (Fase 2).

Costruisce il dataset di regressione per segmenti e intersezioni, calibra i
modelli binomiali negativi (NB2) per ciascuna categoria funzionale e
intersezioni semaforizzate/non semaforizzate, e salva i coefficienti
calibrati insieme alle predizioni E(Y) per ciascun sito.

Il modulo e' organizzato in tre blocchi logici:

1. **Task 2.1** - Preparazione dei dataset di regressione a partire da
   ``incidenti_matched``, ``segmenti`` e ``intersezioni``.
2. **Task 2.2** - Calibrazione dei modelli NB2 con statsmodels.
3. **Task 2.3** - Gestione campioni piccoli: accorpamento automatico
   delle categorie con meno di ``min_siti_per_categoria`` siti.

Output: ``data/processed/spf_models.pkl``.
"""

from __future__ import annotations

import logging
import pickle
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm

from src.config import RADICE_PROGETTO, carica_config

log = logging.getLogger("s03_spf")


# =====================================================================
# Task 2.1 — Preparazione dei dataset di regressione
# =====================================================================


def prepara_dataset_segmenti(
    gdf_segmenti: pd.DataFrame,
    gdf_matched: pd.DataFrame,
    n_anni: float,
) -> pd.DataFrame:
    """Costruisce il dataset di regressione per i segmenti.

    Per ogni segmento calcola il conteggio incidenti (totale e per
    gravita'), unisce gli attributi di traffico/velocita' dal
    GeoDataFrame dei segmenti e aggiunge ``log_tgm``, ``log_lunghezza``
    e ``log_n_anni`` per l'offset.

    Filtra i segmenti con ``tgm_medio <= 0`` o ``lunghezza_m <= 0``.
    """
    # Conteggio incidenti per segmento.
    inc_seg = gdf_matched.loc[
        gdf_matched["match_type"].isin(["segmento", "segmento_toponimo"])
    ].copy()

    conta = (
        inc_seg.groupby("id_match")
        .agg(
            n_incidenti=("id_incidente", "count"),
            n_mortali=("n_morti", lambda s: int((s > 0).sum())),
            n_feriti=(
                "gravita",
                lambda s: int((s == "ferito_lieve").sum()),
            ),
            n_solo_danni=(
                "gravita",
                lambda s: int((s == "solo_danni").sum()),
            ),
            n_pedoni=(
                "natura_incidente",
                lambda s: int(
                    s.str.contains("pedone|pedoni", case=False, na=False).sum()
                ),
            ),
        )
        .rename_axis("id_segmento")
    )

    # Join con gli attributi dei segmenti.
    cols_seg = [
        "id_segmento",
        "toponimo",
        "lunghezza_m",
        "tgm_medio",
        "v85_medio",
        "limite_velocita_medio",
        "eccesso_v85_medio",
        "iqr_norm_medio",
        "iqr_velocita_medio",
        "classe_frc",
        "pgtu_classifica",
        "grande_viabilita",
        "is_extraurbana_cdr",
        "is_extraurbana_altri_enti",
        "isolato",
    ]
    cols_seg = [c for c in cols_seg if c in gdf_segmenti.columns]
    df = gdf_segmenti[cols_seg].copy()
    df = df.set_index("id_segmento")
    df = df.join(conta, how="left")
    df["n_incidenti"] = df["n_incidenti"].fillna(0).astype(int)
    for col in (
        "n_mortali",
        "n_feriti",
        "n_solo_danni",
        "n_pedoni",
    ):
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(int)

    # Covariate logaritmiche.
    df["n_anni"] = float(n_anni)
    df["log_n_anni"] = np.log(float(n_anni))
    df["log_tgm"] = np.log(df["tgm_medio"].clip(lower=1e-6))
    df["log_lunghezza"] = np.log((df["lunghezza_m"] / 1000.0).clip(lower=1e-6))

    # Filtra siti non modellabili.
    mask_valido = (df["tgm_medio"] > 0) & (df["lunghezza_m"] > 0)
    n_esclusi = int((~mask_valido).sum())
    if n_esclusi > 0:
        log.info("Segmenti esclusi (TGM=0 o lung=0): %d", n_esclusi)
    df = df.loc[mask_valido].copy()
    df.index.name = "id_segmento"
    return df.reset_index()


def prepara_dataset_intersezioni(
    gdf_intersezioni: pd.DataFrame,
    gdf_matched: pd.DataFrame,
    gdf_rete: pd.DataFrame,
    n_anni: float,
) -> pd.DataFrame:
    """Costruisce il dataset di regressione per le intersezioni.

    Per ogni intersezione calcola il conteggio incidenti e il flusso
    entrante (somma TGM degli archi convergenti / 2).
    """
    inc_int = gdf_matched.loc[
        gdf_matched["match_type"] == "intersezione"
    ].copy()

    conta = (
        inc_int.groupby("id_match")
        .agg(
            n_incidenti=("id_incidente", "count"),
            n_mortali=("n_morti", lambda s: int((s > 0).sum())),
            n_feriti=(
                "gravita",
                lambda s: int((s == "ferito_lieve").sum()),
            ),
            n_solo_danni=(
                "gravita",
                lambda s: int((s == "solo_danni").sum()),
            ),
            n_pedoni=(
                "natura_incidente",
                lambda s: int(
                    s.str.contains("pedone|pedoni", case=False, na=False).sum()
                ),
            ),
        )
        .rename_axis("id_nodo")
    )

    # Flusso entrante: somma TGM archi convergenti / 2.
    tgm_arco = dict(zip(gdf_rete["id_arco"].values, gdf_rete["tgm"].values))
    archi_col = gdf_intersezioni["archi"]
    flussi = []
    for archi_str in archi_col:
        if isinstance(archi_str, str) and archi_str:
            ids = [int(x) for x in archi_str.split("|")]
        elif isinstance(archi_str, list):
            ids = [int(x) for x in archi_str]
        else:
            ids = []
        somma = sum(tgm_arco.get(a, 0.0) for a in ids)
        flussi.append(somma / 2.0)

    cols_int = ["id_nodo", "n_archi", "is_semaforizzata", "toponimo"]
    cols_int = [c for c in cols_int if c in gdf_intersezioni.columns]
    df = gdf_intersezioni[cols_int].copy()
    df = df.set_index("id_nodo")
    df["flusso_entrante"] = flussi
    df = df.join(conta, how="left")
    df["n_incidenti"] = df["n_incidenti"].fillna(0).astype(int)
    for col in (
        "n_mortali",
        "n_feriti",
        "n_solo_danni",
        "n_pedoni",
    ):
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(int)

    df["n_anni"] = float(n_anni)
    df["log_n_anni"] = np.log(float(n_anni))
    df["log_flusso_entrante"] = np.log(df["flusso_entrante"].clip(lower=1e-6))
    df["n_bracci"] = df["n_archi"]

    mask_valido = df["flusso_entrante"] > 0
    n_esclusi = int((~mask_valido).sum())
    if n_esclusi > 0:
        log.info("Intersezioni escluse (flusso=0): %d", n_esclusi)
    df = df.loc[mask_valido].copy()
    df.index.name = "id_nodo"
    return df.reset_index()


# =====================================================================
# Task 2.3 — Gestione campioni piccoli
# =====================================================================


def accorpa_categorie(
    df: pd.DataFrame,
    colonna_cat: str,
    min_siti: int,
) -> pd.DataFrame:
    """Accorpa le categorie con meno di ``min_siti`` siti in 'ALTRO'.

    Restituisce una copia del DataFrame con la colonna ``categoria_spf``
    che contiene la categoria originale se ha abbastanza siti, oppure
    ``'ALTRO'`` per le categorie accorpate.
    """
    df = df.copy()
    conteggi = df[colonna_cat].value_counts()
    piccole = set(conteggi[conteggi < min_siti].index)
    df["categoria_spf"] = df[colonna_cat].apply(
        lambda v: "ALTRO" if v in piccole or pd.isna(v) else str(v)
    )
    if piccole:
        log.info(
            "Categorie accorpate in 'ALTRO' (%s < %d siti): %s",
            colonna_cat,
            min_siti,
            sorted(piccole),
        )
    # Anche i NaN vanno in ALTRO.
    df.loc[df[colonna_cat].isna(), "categoria_spf"] = "ALTRO"
    return df


# =====================================================================
# Task 2.2 — Calibrazione modelli NB2
# =====================================================================


def calibra_nb2(
    df: pd.DataFrame,
    formula_covariate: list[str],
    offset_col: str = "log_n_anni",
) -> dict[str, Any]:
    """Calibra un modello NB2 (binomiale negativa) con statsmodels.

    Usa ``statsmodels.discrete.NegativeBinomialP(p=2)`` che stima il
    parametro di sovradispersione ``alpha`` direttamente dai dati via MLE
    (a differenza del GLM con ``NegativeBinomial(alpha=...)`` che richiede
    alpha fissato a priori e restituisce la dispersione di Pearson, non la
    sovradispersione NB2).

    Filtra preventivamente le righe con NaN nelle covariate o nell'offset
    per garantire che ``df`` sia il campione effettivo del fit.

    Restituisce un dizionario con:
    - ``coefficienti``: dict nome -> valore (covariate, intercetta)
    - ``p_values``: dict nome -> p-value
    - ``alpha``: sovradispersione NB2 stimata (Var(Y) = mu + alpha*mu^2)
    - ``k``: ``1/alpha`` (parametro usato dall'Empirical Bayes)
    - ``aic``, ``bic``: criteri informativi
    - ``n_siti``: numero di osservazioni nel fit
    - ``converged``: bool
    """
    cols_richieste = list(formula_covariate) + [offset_col, "n_incidenti"]
    df_fit = df.dropna(subset=cols_richieste).copy()
    if len(df_fit) < len(df):
        log.info(
            "  dropna su %s: %d -> %d righe",
            cols_richieste, len(df), len(df_fit),
        )

    if len(df_fit) < 10:
        log.warning(
            "Troppo pochi siti (%d) per calibrare NB2, salto", len(df_fit)
        )
        return {"converged": False, "n_siti": len(df_fit)}

    y = df_fit["n_incidenti"].to_numpy(dtype=float)
    X = sm.add_constant(df_fit[formula_covariate].to_numpy(dtype=float))
    offset = df_fit[offset_col].to_numpy(dtype=float)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # Warm-start dai coefficienti di un GLM Poisson: rende il fit NB2
        # robusto anche su categorie con bassa sovradispersione.
        start: np.ndarray | None
        try:
            poisson_fit = sm.GLM(
                y, X, family=sm.families.Poisson(), offset=offset
            ).fit(maxiter=100)
            start = np.concatenate([poisson_fit.params, [0.1]])
        except Exception:
            start = None

        risultato = None
        for metodo in ("newton", "bfgs", "nm"):
            try:
                fit_kwargs: dict[str, Any] = dict(
                    disp=0, maxiter=500, method=metodo
                )
                if start is not None:
                    fit_kwargs["start_params"] = start
                cand = sm.NegativeBinomialP(y, X, p=2, offset=offset).fit(
                    **fit_kwargs
                )
            except Exception:
                continue
            alpha_cand = float(cand.params[-1])
            converged_cand = bool(cand.mle_retvals.get("converged", False))
            # Accetta anche fit "non convergenti" se alpha e' finito e
            # non patologico (NM spesso non setta il flag).
            if np.isfinite(alpha_cand) and -1e-3 < alpha_cand < 1e6:
                risultato = cand
                if converged_cand and alpha_cand > 0:
                    break

    if risultato is None:
        # Fallback: dati senza sovradispersione apprezzabile -> GLM Poisson,
        # k = inf (peso EB w -> 0 quando E*k -> inf, EB -> O: nessuno shrinkage).
        if start is None:
            log.warning("Calibrazione NB2 fallita e Poisson non disponibile")
            return {"converged": False, "n_siti": len(df_fit)}
        log.info(
            "  NB2 non stabile (sovradispersione trascurabile): fallback Poisson"
        )
        nomi = ["const"] + list(formula_covariate)
        coefficienti = dict(zip(nomi, poisson_fit.params.tolist()))
        try:
            p_values = dict(zip(nomi, poisson_fit.pvalues.tolist()))
        except Exception:
            p_values = {n: float("nan") for n in nomi}
        predetti = np.asarray(poisson_fit.predict(X, offset=offset))
        return {
            "modello": poisson_fit,
            "coefficienti": coefficienti,
            "p_values": p_values,
            "alpha": 1e-6,
            "k": 1.0 / 1e-6,
            "aic": float(poisson_fit.aic) if hasattr(poisson_fit, "aic") else None,
            "bic": None,
            "n_siti": int(len(df_fit)),
            "predetti": predetti,
            "converged": True,
            "nomi_covariate": list(formula_covariate),
            "famiglia": "Poisson",
        }

    # Parametri di regressione: tutti tranne l'ultimo (che e' alpha).
    nomi = ["const"] + list(formula_covariate)
    coef_array = np.asarray(risultato.params[:-1])
    try:
        pval_array = np.asarray(risultato.pvalues[:-1])
        p_values = dict(zip(nomi, pval_array.tolist()))
    except Exception:
        # Hessian non invertibile: p-values non disponibili.
        p_values = {n: float("nan") for n in nomi}
    coefficienti = dict(zip(nomi, coef_array.tolist()))

    # alpha: ultimo parametro. Per NB2: Var(Y) = mu + alpha*mu^2. Clip
    # inferiore per evitare k -> inf (sovradispersione trascurabile).
    alpha = max(float(risultato.params[-1]), 1e-6)
    k = 1.0 / alpha

    predetti = np.asarray(risultato.predict(X, offset=offset))

    return {
        "modello": risultato,
        "coefficienti": coefficienti,
        "p_values": p_values,
        "alpha": alpha,
        "k": k,
        "aic": float(risultato.aic) if hasattr(risultato, "aic") else None,
        "bic": float(risultato.bic) if hasattr(risultato, "bic") else None,
        "n_siti": int(len(df_fit)),
        "predetti": predetti,
        "converged": True,
        "nomi_covariate": list(formula_covariate),
    }


def calibra_nb2_per_categoria(
    df: pd.DataFrame,
    col_categoria: str,
    formula_covariate: list[str],
    offset_col: str = "log_n_anni",
) -> dict[str, dict[str, Any]]:
    """Calibra un modello NB2 separato per ogni valore di ``col_categoria``.

    Restituisce ``{categoria: risultato_calibra_nb2}``.
    """
    risultati: dict[str, dict[str, Any]] = {}
    categorie = sorted(df[col_categoria].dropna().unique())
    for cat in categorie:
        sub = df.loc[df[col_categoria] == cat].copy()
        log.info(
            "  Calibrazione '%s': %d siti, %d incidenti totali",
            cat,
            len(sub),
            int(sub["n_incidenti"].sum()),
        )
        ris = calibra_nb2(sub, formula_covariate, offset_col)
        if ris["converged"]:
            log.info(
                "    coefficienti: %s",
                {k: f"{v:.4f}" for k, v in ris["coefficienti"].items()},
            )
            log.info("    alpha=%.4f, k=%.4f", ris["alpha"], ris["k"])
        else:
            log.warning("    modello non convergente per '%s'", cat)
        risultati[str(cat)] = ris
    return risultati


def applica_predizioni(
    df: pd.DataFrame,
    risultati_per_cat: dict[str, dict[str, Any]],
    col_categoria: str,
) -> pd.DataFrame:
    """Aggiunge le colonne ``E_i`` (predetto SPF) e ``k_spf`` al DataFrame.

    Le predizioni vengono calcolate solo per i siti senza NaN nelle
    covariate del modello adottato; i siti con covariate mancanti hanno
    ``E_i = NaN`` e vengono di conseguenza esclusi dall'EB.
    """
    df = df.copy()
    df["E_i"] = np.nan
    df["k_spf"] = np.nan
    df["spf_categoria"] = df[col_categoria].astype(str)

    for cat, ris in risultati_per_cat.items():
        if not ris.get("converged", False):
            continue
        mask_cat = df[col_categoria] == cat
        if not mask_cat.any():
            continue

        formula = ris["nomi_covariate"]
        cols_richieste = list(formula) + ["log_n_anni"]
        mask_valido = mask_cat & df[cols_richieste].notna().all(axis=1)
        if not mask_valido.any():
            continue

        X = sm.add_constant(
            df.loc[mask_valido, formula].to_numpy(dtype=float),
            has_constant="add",
        )
        offset = df.loc[mask_valido, "log_n_anni"].to_numpy(dtype=float)
        predetti = ris["modello"].predict(X, offset=offset)
        df.loc[mask_valido, "E_i"] = np.asarray(predetti)
        df.loc[mask_valido, "k_spf"] = ris["k"]

    return df


# =====================================================================
# Riassunto e salvataggio
# =====================================================================


def riassumi_spf(
    risultati_seg: dict[str, dict[str, Any]],
    risultati_int: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Riassunto dei modelli SPF calibrati."""
    r: dict[str, Any] = {"segmenti": {}, "intersezioni": {}}
    for cat, ris in risultati_seg.items():
        r["segmenti"][cat] = {
            "n_siti": ris.get("n_siti", 0),
            "converged": ris.get("converged", False),
            "alpha": ris.get("alpha"),
            "k": ris.get("k"),
            "coefficienti": ris.get("coefficienti"),
        }
    for cat, ris in risultati_int.items():
        r["intersezioni"][cat] = {
            "n_siti": ris.get("n_siti", 0),
            "converged": ris.get("converged", False),
            "alpha": ris.get("alpha"),
            "k": ris.get("k"),
            "coefficienti": ris.get("coefficienti"),
        }
    return r


def salva_modelli(
    risultati_seg: dict[str, dict[str, Any]],
    risultati_int: dict[str, dict[str, Any]],
    df_seg: pd.DataFrame,
    df_int: pd.DataFrame,
    percorso: Path,
) -> None:
    """Salva i risultati SPF in un file pickle."""
    percorso.parent.mkdir(parents=True, exist_ok=True)

    # Rimuovi l'oggetto modello statsmodels dalla serializzazione —
    # e' pesante e non servira'; conserviamo solo coefficienti e k.
    def _clean(ris: dict) -> dict:
        return {k: v for k, v in ris.items() if k != "modello"}

    payload = {
        "risultati_segmenti": {
            cat: _clean(r) for cat, r in risultati_seg.items()
        },
        "risultati_intersezioni": {
            cat: _clean(r) for cat, r in risultati_int.items()
        },
        "df_segmenti_spf": df_seg,
        "df_intersezioni_spf": df_int,
    }
    with open(percorso, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    log.info("Modelli SPF salvati: %s", percorso)


# =====================================================================
# Pipeline principale
# =====================================================================


def main(config: dict[str, Any]) -> None:
    """Calibra le SPF e salva i modelli."""
    import geopandas as gpd

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # --- Caricamento ---
    paths = config["paths"]["interim"]
    seg_path = RADICE_PROGETTO / paths["segmenti"]
    int_path = RADICE_PROGETTO / paths["intersezioni"]
    match_path = RADICE_PROGETTO / paths["incidenti_matched"]
    rete_path = RADICE_PROGETTO / paths["rete_tomtom_prep"]

    log.info("Caricamento segmenti da %s", seg_path)
    gdf_segmenti = gpd.read_file(seg_path, layer="segmenti")
    log.info("Caricamento intersezioni da %s", int_path)
    gdf_intersezioni = gpd.read_file(int_path, layer="intersezioni")
    log.info("Caricamento incidenti matched da %s", match_path)
    gdf_matched = gpd.read_file(match_path, layer="incidenti_matched")
    log.info("Caricamento rete da %s", rete_path)
    gdf_rete = gpd.read_file(rete_path, layer="rete_prep")

    # --- Filtro temporale sugli incidenti ---
    anni_sel = config.get("spf", {}).get("anni_incidenti")
    if anni_sel:
        n_prima = len(gdf_matched)
        gdf_matched = gdf_matched.loc[gdf_matched["anno"].isin(anni_sel)].copy()
        log.info(
            "Filtro temporale: anni %s -> %d incidenti (da %d)",
            anni_sel, len(gdf_matched), n_prima,
        )

    # --- n_anni: lunghezza del periodo di osservazione ---
    # Si usa il numero di anni di calendario coperti, NON nunique() degli anni
    # con incidenti: un anno senza incidenti osservati va comunque conteggiato
    # nell'offset (altrimenti si gonfiano artificialmente le predizioni SPF).
    if anni_sel:
        n_anni = float(len(anni_sel))
        log.info(
            "Periodo SPF (da config.spf.anni_incidenti): %d anni (%s)",
            int(n_anni), anni_sel,
        )
    else:
        abbinati = gdf_matched.loc[gdf_matched["match_type"] != "non_abbinato"]
        anni_validi = abbinati["anno"].dropna()
        if len(anni_validi) == 0:
            raise RuntimeError("Nessun incidente abbinato: impossibile derivare il periodo SPF")
        anno_min, anno_max = int(anni_validi.min()), int(anni_validi.max())
        n_anni = float(anno_max - anno_min + 1)
        log.info(
            "Periodo SPF (da estensione dati matched): %d-%d -> %d anni",
            anno_min, anno_max, int(n_anni),
        )

    # --- Esclusione segmenti di altri enti ---
    if "is_extraurbana_altri_enti" in gdf_segmenti.columns:
        n_altri = int(gdf_segmenti["is_extraurbana_altri_enti"].fillna(False).sum())
        if n_altri > 0:
            gdf_segmenti = gdf_segmenti.loc[
                ~gdf_segmenti["is_extraurbana_altri_enti"].fillna(False)
            ].copy()
            log.info(
                "Esclusi %d segmenti di altri enti (autostrade, ANAS, ecc.)",
                n_altri,
            )

    # --- Task 2.1: preparazione dataset ---
    log.info("=== Task 2.1: preparazione dataset ===")
    df_seg = prepara_dataset_segmenti(gdf_segmenti, gdf_matched, n_anni)
    log.info(
        "Dataset segmenti: %d siti, %d incidenti totali",
        len(df_seg),
        int(df_seg["n_incidenti"].sum()),
    )

    df_int = prepara_dataset_intersezioni(
        gdf_intersezioni, gdf_matched, gdf_rete, n_anni
    )
    log.info(
        "Dataset intersezioni: %d siti, %d incidenti totali",
        len(df_int),
        int(df_int["n_incidenti"].sum()),
    )

    # --- Task 2.3: categorizzazione e accorpamento ---
    min_siti = int(config["spf"]["min_siti_per_categoria"])

    log.info("=== Task 2.3: accorpamento categorie ===")

    # Assegna categoria SPF ai segmenti.
    # Priorita': extraurbana_cdr > pgtu_classifica > LOCALE (ex-ALTRO).
    def _categoria_segmento(row: pd.Series) -> str:
        if row.get("is_extraurbana_cdr", False):
            return "EXTRAURBANA"
        pgtu = row.get("pgtu_classifica")
        if pd.notna(pgtu) and str(pgtu).strip():
            cat = str(pgtu).strip().upper()
            if cat == "S":
                return "IQ"
            return cat
        return "LOCALE"

    if "is_extraurbana_cdr" in df_seg.columns:
        df_seg["categoria_spf"] = df_seg.apply(_categoria_segmento, axis=1)
    else:
        df_seg = accorpa_categorie(df_seg, "pgtu_classifica", min_siti)
        df_seg.loc[df_seg["categoria_spf"] == "S", "categoria_spf"] = "IQ"
        df_seg["categoria_spf"] = df_seg["categoria_spf"].replace("ALTRO", "LOCALE")

    # Accorpa categorie troppo piccole in LOCALE.
    conteggi = df_seg["categoria_spf"].value_counts()
    piccole = set(conteggi[conteggi < min_siti].index) - {"LOCALE"}
    if piccole:
        log.info("Categorie accorpate in LOCALE (< %d siti): %s", min_siti, sorted(piccole))
        df_seg.loc[df_seg["categoria_spf"].isin(piccole), "categoria_spf"] = "LOCALE"

    log.info(
        "Categorie segmenti: %s",
        df_seg["categoria_spf"].value_counts().to_dict(),
    )

    # Intersezioni: categoria = semaforizzata / non_semaforizzata.
    df_int["categoria_spf"] = df_int["is_semaforizzata"].apply(
        lambda v: "semaforizzata" if v else "non_semaforizzata"
    )
    log.info(
        "Categorie intersezioni: %s",
        df_int["categoria_spf"].value_counts().to_dict(),
    )

    # --- Task 2.2: calibrazione modelli ---
    log.info("=== Task 2.2: calibrazione SPF segmenti ===")
    covariate_seg = ["log_tgm", "log_lunghezza"]
    risultati_seg = calibra_nb2_per_categoria(
        df_seg, "categoria_spf", covariate_seg
    )

    log.info("=== Task 2.2: calibrazione SPF intersezioni ===")
    covariate_int = ["log_flusso_entrante"]
    risultati_int = calibra_nb2_per_categoria(
        df_int, "categoria_spf", covariate_int
    )

    # Modelli estesi: aggiungi covariate e confronta AIC sullo STESSO campione
    # del modello esteso (il base viene rifittato escludendo le righe con NaN
    # nelle covariate estese, altrimenti l'AIC non e' confrontabile).
    log.info("=== Modelli estesi segmenti ===")
    covariate_estese_seg = ["log_tgm", "log_lunghezza", "v85_medio", "iqr_velocita_medio"]
    risultati_seg_ext = calibra_nb2_per_categoria(
        df_seg, "categoria_spf", covariate_estese_seg
    )
    for cat in risultati_seg:
        r_ext = risultati_seg_ext.get(cat, {})
        if not r_ext.get("converged"):
            continue
        # Rifitto il base sullo stesso sample del modello esteso.
        sub = df_seg.loc[df_seg["categoria_spf"] == cat].dropna(
            subset=covariate_estese_seg + ["log_n_anni"]
        )
        r_base_same = calibra_nb2(sub, covariate_seg, "log_n_anni")
        if not r_base_same.get("converged"):
            continue
        aic_base = r_base_same.get("aic")
        aic_ext = r_ext.get("aic")
        if aic_base is not None and aic_ext is not None and aic_ext < aic_base:
            log.info(
                "  '%s': modello esteso migliore (AIC %.1f < %.1f su n=%d), adottato",
                cat, aic_ext, aic_base, r_ext["n_siti"],
            )
            risultati_seg[cat] = r_ext

    log.info("=== Modelli estesi intersezioni ===")
    covariate_estese_int = ["log_flusso_entrante", "n_bracci"]
    risultati_int_ext = calibra_nb2_per_categoria(
        df_int, "categoria_spf", covariate_estese_int
    )
    for cat in risultati_int:
        r_ext = risultati_int_ext.get(cat, {})
        if not r_ext.get("converged"):
            continue
        sub = df_int.loc[df_int["categoria_spf"] == cat].dropna(
            subset=covariate_estese_int + ["log_n_anni"]
        )
        r_base_same = calibra_nb2(sub, covariate_int, "log_n_anni")
        if not r_base_same.get("converged"):
            continue
        aic_base = r_base_same.get("aic")
        aic_ext = r_ext.get("aic")
        if aic_base is not None and aic_ext is not None and aic_ext < aic_base:
            log.info(
                "  '%s': modello esteso migliore (AIC %.1f < %.1f su n=%d), adottato",
                cat, aic_ext, aic_base, r_ext["n_siti"],
            )
            risultati_int[cat] = r_ext

    # --- Applica predizioni ---
    df_seg = applica_predizioni(df_seg, risultati_seg, "categoria_spf")
    df_int = applica_predizioni(df_int, risultati_int, "categoria_spf")

    n_seg_pred = int(df_seg["E_i"].notna().sum())
    n_int_pred = int(df_int["E_i"].notna().sum())
    log.info(
        "Predizioni calcolate: %d/%d segmenti, %d/%d intersezioni",
        n_seg_pred,
        len(df_seg),
        n_int_pred,
        len(df_int),
    )

    # --- Riassunto ---
    riassunto = riassumi_spf(risultati_seg, risultati_int)
    log.info("Riassunto SPF:")
    for tipo in ("segmenti", "intersezioni"):
        for cat, info in riassunto[tipo].items():
            log.info(
                "  %s / %s: n=%d conv=%s k=%s",
                tipo,
                cat,
                info["n_siti"],
                info["converged"],
                f"{info['k']:.4f}" if info.get("k") is not None else "N/A",
            )

    # --- Salvataggio ---
    out_path = RADICE_PROGETTO / config["paths"]["processed"]["spf_models"]
    salva_modelli(risultati_seg, risultati_int, df_seg, df_int, out_path)


if __name__ == "__main__":
    main(carica_config())
