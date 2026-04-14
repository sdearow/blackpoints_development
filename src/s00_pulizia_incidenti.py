"""Step 00 - Pulizia del database incidenti (Fase 0, Task 0.1).

Importa il dataset grezzo degli incidenti (file ``Incidenti_1_parte*.csv`` e
``Incidenti_2.csv``), standardizza i campi (coordinate, gravita', data/ora,
toponomastica), calcola i flag di affidabilita' della geocodifica e salva un
GeoPackage unico.

Convenzioni dei file di input (schema osservato dai CSV del Comune di Roma):
- ``Incidenti_1_parte*.csv`` contengono gli incidenti storici
  geolocalizzati dal 2008 al 2021, agganciati alla rete (campi ``idta1``,
  ``idmnet1`` popolati).
- ``Incidenti_2.csv`` contiene gli incidenti 2024+, geolocalizzati ma non
  ancora agganciati alla rete: vengono flaggati ``da_rigeolocalizzare``.

Le coordinate sono nel sistema italiano Gauss-Boaga zona 2
(``EPSG:3004``) e vengono riproiettate al CRS metrico di lavoro configurato
in ``config.yaml`` (default UTM zona 33N, ``EPSG:32633``).

Le note testuali (``note_semaforo``, ``danni_a_cose``) sono preservate per
consentire debug e interpretazione manuale dei casi dubbi.
"""

from __future__ import annotations

import glob
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.config import RADICE_PROGETTO, carica_config

log = logging.getLogger("s00_pulizia_incidenti")

# ---------------------------------------------------------------------------
# Mappatura colonne CSV grezze -> nomi puliti del progetto
# ---------------------------------------------------------------------------

MAPPATURA_COLONNE: dict[str, str] = {
    "idprotocollo": "id_incidente",
    "dataoraincidente": "data_ora",
    "anno": "anno",
    "num_morti": "n_morti",
    "num_feriti": "n_feriti",
    "num_riservata": "n_riservata",
    "num_illesi": "n_illesi",
    "num_veicoli": "n_veicoli",
    "costo_sociale": "costo_sociale",
    "flow": "flow",
    "speed": "speed",
    "x": "x",
    "y": "y",
    "idta1": "id_ta1",
    "idta2": "id_ta2",
    "idmnet1": "id_mnet1",
    "idmnet2": "id_mnet2",
    "municipio": "municipio",
    "municipio13": "municipio13",
    "ok": "ok",
    "approx": "approx",
    "strada1": "strada1",
    "strada2": "strada2",
    "strada12": "strada12",
    "idlocalizzazione1": "id_localizzazione1",
    "localizzazione1": "localizzazione1",
    "idlocalizzazione2": "id_localizzazione2",
    "localizzazione2": "localizzazione2",
    "strada02": "strada02",
    "chilometrica": "chilometrica",
    "daspecificare": "da_specificare",
    "idimpiantosemaforico": "id_semaforo",
    "impiantosemaforico": "impianto_semaforico",
    "noteimpiantosemaforico": "note_semaforo",
    "idtronco": "id_tronco",
    "tronco": "tronco",
    "idparticolaritastrada": "id_particolarita_strada",
    "particolaritastrada": "particolarita_strada",
    "idtipostrada": "id_tipo_strada",
    "tipostrada": "tipo_strada",
    "idpavimentazione": "id_pavimentazione",
    "pavimentazione": "pavimentazione",
    "idsegnaletica": "id_segnaletica",
    "segnaletica": "segnaletica",
    "idfondostradale": "id_fondo_stradale",
    "fondostradale": "fondo_stradale",
    "idcondizioneatmosferica": "id_condizione_atmosferica",
    "condizioneatmosferica": "condizione_atmosferica",
    "idtraffico": "id_traffico",
    "traffico": "traffico",
    "idvisibilita": "id_visibilita",
    "visibilita": "visibilita",
    "idilluminazione": "id_illuminazione",
    "illuminazione": "illuminazione",
    "idnaturaincidente": "id_natura_incidente",
    "naturaincidente": "natura_incidente",
    "danniacoseyn": "danni_a_cose_yn",
    "danniacose": "danni_a_cose",
    "confermato": "confermato",
    "dataconferma": "data_conferma",
}

# Colonne testuali (incluse le "note") da preservare per debug.
# Le altre colonne del CSV vengono convertite al tipo appropriato.
COLONNE_TESTUALI_PRESERVATE = {
    "strada1",
    "strada2",
    "strada12",
    "strada02",
    "localizzazione1",
    "localizzazione2",
    "da_specificare",
    "chilometrica",
    "impianto_semaforico",
    "note_semaforo",
    "tronco",
    "particolarita_strada",
    "tipo_strada",
    "pavimentazione",
    "segnaletica",
    "fondo_stradale",
    "condizione_atmosferica",
    "traffico",
    "visibilita",
    "illuminazione",
    "natura_incidente",
    "danni_a_cose",
}

COLONNE_INTERE = [
    "anno",
    "n_morti",
    "n_feriti",
    "n_riservata",
    "n_illesi",
    "n_veicoli",
    "costo_sociale",
    "municipio",
    "municipio13",
    "id_ta1",
    "id_ta2",
    "id_mnet1",
    "id_mnet2",
    "id_localizzazione1",
    "id_localizzazione2",
    "id_semaforo",
    "id_tronco",
    "id_particolarita_strada",
    "id_tipo_strada",
    "id_pavimentazione",
    "id_segnaletica",
    "id_fondo_stradale",
    "id_condizione_atmosferica",
    "id_traffico",
    "id_visibilita",
    "id_illuminazione",
    "id_natura_incidente",
]

COLONNE_FLOAT = ["flow", "speed", "x", "y"]

# ---------------------------------------------------------------------------
# Normalizzazione toponomastica
# ---------------------------------------------------------------------------

# Abbreviazioni tipiche dei nomi di strada nei dataset di Roma.
# Il pattern usa word boundary per non sostituire pezzi di parole.
# I pattern che terminano con ``.`` usano un lookahead ``(?=\s|$)`` invece
# di ``\b`` perche' dopo il punto c'e' un non-word (lo spazio) e ``\b`` non
# scatta tra due non-word.
ABBREVIAZIONI_STRADA: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bV\.LE\b", re.IGNORECASE), "Viale"),
    (re.compile(r"\bP\.ZZA\b", re.IGNORECASE), "Piazza"),
    (re.compile(r"\bP\.ZA\b", re.IGNORECASE), "Piazza"),
    (re.compile(r"\bP\.LE\b", re.IGNORECASE), "Piazzale"),
    (re.compile(r"\bL\.GO\b", re.IGNORECASE), "Largo"),
    (re.compile(r"\bC\.SO\b", re.IGNORECASE), "Corso"),
    (re.compile(r"\bV\.LO\b", re.IGNORECASE), "Vicolo"),
    (re.compile(r"\bVL\.(?=\s|$)", re.IGNORECASE), "Viale"),
    (re.compile(r"\bV\.(?=\s|$)", re.IGNORECASE), "Via"),
    (re.compile(r"\bSS\b"), "Strada Statale"),
    (re.compile(r"\bSP\b"), "Strada Provinciale"),
]


def normalizza_nome_strada(valore: Any) -> str | None:
    """Standardizza un nome di strada.

    - Espande le abbreviazioni piu' comuni (``V.`` -> ``Via``, ``P.le`` ->
      ``Piazzale``, ...)
    - Collassa gli spazi multipli
    - Applica Title Case per uniformare le maiuscole

    Restituisce ``None`` per valori vuoti o ``NaN``.
    """

    if valore is None:
        return None
    if isinstance(valore, float) and pd.isna(valore):
        return None
    testo = str(valore).strip()
    if not testo:
        return None
    for pattern, sostituto in ABBREVIAZIONI_STRADA:
        testo = pattern.sub(sostituto, testo)
    testo = re.sub(r"\s+", " ", testo).strip()
    # Title case intelligente: preserva sigle brevi tipo "SS" dopo la
    # sostituzione. Applichiamo .title() poi ripristiniamo le parole che
    # devono restare in minuscolo (di, del, della, etc.).
    minuscole = {
        "Di",
        "Del",
        "Della",
        "Dei",
        "Delle",
        "Da",
        "Dal",
        "Dalla",
        "Dalle",
        "Dagli",
        "A",
        "Al",
        "Alla",
        "Alle",
        "Agli",
        "In",
        "Con",
        "Su",
        "Per",
        "E",
        "Ed",
        "O",
    }
    parole = testo.title().split()
    for i, parola in enumerate(parole):
        if i > 0 and parola in minuscole:
            parole[i] = parola.lower()
    return " ".join(parole)


# ---------------------------------------------------------------------------
# Caricamento
# ---------------------------------------------------------------------------


def _leggi_csv(percorso: Path) -> pd.DataFrame:
    """Legge un singolo CSV incidenti con i tipi di base."""
    log.info("Lettura %s", percorso.name)
    # Leggiamo tutto come stringa e convertiamo in seguito: nei CSV reali i
    # numeri possono avere virgole/spazi e i mancanti sono stringhe vuote.
    return pd.read_csv(
        percorso,
        dtype=str,
        keep_default_na=True,
        na_values=["", " ", "NA", "NULL"],
        low_memory=False,
    )


def carica_incidenti_grezzi(config: dict[str, Any]) -> pd.DataFrame:
    """Carica tutti i CSV degli incidenti e li concatena in un unico DataFrame.

    Aggiunge due colonne di tracciabilita':
    - ``source_file``: nome del file di provenienza
    - ``da_rigeolocalizzare``: ``True`` per i record di ``Incidenti_2.csv``
    """

    paths_cfg = config["paths"]["raw"]
    directory = RADICE_PROGETTO / paths_cfg["incidenti_dir"]
    if not directory.is_dir():
        raise FileNotFoundError(f"Directory incidenti non trovata: {directory}")

    pattern_pre = str(directory / paths_cfg["incidenti_pre2022_glob"])
    file_pre2022 = sorted(glob.glob(pattern_pre))
    file_post2022 = directory / paths_cfg["incidenti_post2022"]

    if not file_pre2022:
        raise FileNotFoundError(
            f"Nessun file pre-2022 trovato con pattern {pattern_pre}"
        )

    frame_dfs: list[pd.DataFrame] = []
    for percorso in file_pre2022:
        df = _leggi_csv(Path(percorso))
        df["source_file"] = os.path.basename(percorso)
        df["da_rigeolocalizzare"] = False
        frame_dfs.append(df)

    if file_post2022.is_file():
        df = _leggi_csv(file_post2022)
        df["source_file"] = file_post2022.name
        df["da_rigeolocalizzare"] = True
        frame_dfs.append(df)
    else:
        log.warning("File post-2022 non trovato: %s", file_post2022)

    df_tot = pd.concat(frame_dfs, ignore_index=True)
    log.info("Totale righe grezze caricate: %d", len(df_tot))
    return df_tot


# ---------------------------------------------------------------------------
# Standardizzazione
# ---------------------------------------------------------------------------


def standardizza_colonne(df: pd.DataFrame) -> pd.DataFrame:
    """Rinomina colonne e converte tipi.

    - Applica :data:`MAPPATURA_COLONNE`
    - Casta colonne numeriche a int/float (con NaN sicuri)
    - Normalizza i nomi di strada
    - Converte ``confermato`` e ``ok`` in booleani
    - Converte ``danni_a_cose_yn`` in booleano
    """

    df = df.rename(columns=MAPPATURA_COLONNE).copy()

    # Conversioni numeriche.
    for col in COLONNE_INTERE:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in COLONNE_FLOAT:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Booleani.
    def _a_bool(valore: Any) -> bool | None:
        if valore is None:
            return None
        if isinstance(valore, float) and pd.isna(valore):
            return None
        testo = str(valore).strip().lower()
        if testo in {"t", "true", "1", "si", "sì", "y", "yes"}:
            return True
        if testo in {"f", "false", "0", "no", "n"}:
            return False
        return None

    for col in ("ok", "confermato", "danni_a_cose_yn"):
        if col in df.columns:
            df[col] = df[col].map(_a_bool).astype("boolean")

    # Normalizza nomi di strada.
    for col in ("strada1", "strada2", "strada12", "strada02"):
        if col in df.columns:
            df[col] = df[col].map(normalizza_nome_strada)

    return df


def parsa_datetime(df: pd.DataFrame) -> pd.DataFrame:
    """Converte ``data_ora`` a datetime ed estrae anno/mese/dow/ora/fascia."""

    df = df.copy()
    df["data_ora"] = pd.to_datetime(df["data_ora"], errors="coerce")
    df["data_conferma"] = pd.to_datetime(df["data_conferma"], errors="coerce", utc=True)

    # Se il CSV non ha un valore di anno coerente, lo ricalcoliamo dal datetime.
    dt = df["data_ora"]
    df["anno"] = df["anno"].fillna(dt.dt.year).astype("Int64")
    df["mese"] = dt.dt.month.astype("Int64")
    df["giorno_settimana"] = dt.dt.dayofweek.astype("Int64")  # 0=lunedi'
    df["ora"] = dt.dt.hour.astype("Int64")

    def _fascia(ora: Any) -> str | None:
        if pd.isna(ora):
            return None
        o = int(ora)
        if 0 <= o < 6:
            return "notte"
        if 6 <= o < 12:
            return "mattina"
        if 12 <= o < 18:
            return "pomeriggio"
        return "sera"

    df["fascia_oraria"] = df["ora"].map(_fascia)
    return df


def classifica_gravita(df: pd.DataFrame) -> pd.DataFrame:
    """Crea il campo ``gravita`` in 3 livelli.

    Dato che il CSV non distingue feriti gravi da feriti lievi, adottiamo una
    classificazione conservativa (tutti i feriti sono ``ferito_lieve``). Il
    campo ``n_riservata`` (prognosi riservata) viene preservato nel dataset
    ma non usato per la classificazione.

    Livelli:
    - ``mortale``       se ``n_morti > 0``
    - ``ferito_lieve``  se ``n_feriti > 0`` (e ``n_morti == 0``)
    - ``solo_danni``    altrimenti
    """

    df = df.copy()
    n_morti = df["n_morti"].fillna(0)
    n_feriti = df["n_feriti"].fillna(0)

    gravita = pd.Series("solo_danni", index=df.index, dtype="object")
    gravita[n_feriti > 0] = "ferito_lieve"
    gravita[n_morti > 0] = "mortale"
    df["gravita"] = gravita.astype("category")
    return df


def calcola_flag_qualita(df: pd.DataFrame) -> pd.DataFrame:
    """Assegna un flag di affidabilita' della geocodifica.

    Il campo discriminante per la specificita' della localizzazione e'
    ``localizzazione2`` (``localizzazione1`` contiene invece il tipo di
    strada: Urbana, Provinciale, ...).

    Il campo ``approx`` nei CSV e' l'errore stimato in metri della
    geocodifica (``NaN`` = errore non indicato = posizione esatta).

    Livelli di qualita':
    - ``alta``:   coordinate valide, ``ok = True``, ``approx`` nullo e
                  ``localizzazione2`` contiene un riferimento specifico
                  (intersezione, in corrispondenza di, in prossimita').
    - ``media``:  coordinate valide, ``ok = True`` ma una delle condizioni
                  sopra non e' soddisfatta.
    - ``bassa``:  coordinate mancanti o ``ok = False``.
    """

    df = df.copy()
    coord_valide = df["x"].notna() & df["y"].notna()
    ok_vero = df["ok"].fillna(False).astype(bool)

    localizzazione = df.get("localizzazione2")
    if localizzazione is None:
        localizzazione_specifica = pd.Series(False, index=df.index)
    else:
        loc = localizzazione.fillna("").astype(str).str.lower()
        localizzazione_specifica = (
            loc.str.contains("intersezione", na=False)
            | loc.str.contains("corrispondenza", na=False)
            | loc.str.contains("prossim", na=False)
        )

    approx_nullo = df["approx"].isna() | (df["approx"].astype(str).str.strip() == "")

    flag = pd.Series("bassa", index=df.index, dtype="object")
    flag[(coord_valide & ok_vero).fillna(False)] = "media"
    flag[
        (coord_valide & ok_vero & approx_nullo & localizzazione_specifica).fillna(False)
    ] = "alta"
    df["flag_qualita"] = flag.astype("category")
    return df


# ---------------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------------


def crea_geodataframe(df: pd.DataFrame, crs_origine: str) -> gpd.GeoDataFrame:
    """Crea un GeoDataFrame con geometria Point da ``x``, ``y``.

    Le righe con coordinate mancanti vengono scartate (ma restano tracciate
    nel log con il conteggio complessivo).
    """

    coord_valide = df["x"].notna() & df["y"].notna()
    n_scartati = int((~coord_valide).sum())
    if n_scartati:
        log.warning("Scartate %d righe per coordinate mancanti", n_scartati)

    df_valido = df.loc[coord_valide].copy()
    geometry = [Point(xy) for xy in zip(df_valido["x"], df_valido["y"])]
    return gpd.GeoDataFrame(df_valido, geometry=geometry, crs=crs_origine)


def riproietta(gdf: gpd.GeoDataFrame, crs_target: str) -> gpd.GeoDataFrame:
    """Riproietta il GeoDataFrame verso ``crs_target``."""
    return gdf.to_crs(crs_target)


# ---------------------------------------------------------------------------
# Filtri
# ---------------------------------------------------------------------------


def filtra_periodo(
    gdf: gpd.GeoDataFrame,
    anno_inizio: int | None,
    anno_fine: int | None,
) -> gpd.GeoDataFrame:
    """Filtra per anno. Se entrambi gli estremi sono ``None``, e' un no-op."""
    if anno_inizio is None and anno_fine is None:
        return gdf
    mask = pd.Series(True, index=gdf.index)
    if anno_inizio is not None:
        mask &= gdf["anno"] >= anno_inizio
    if anno_fine is not None:
        mask &= gdf["anno"] <= anno_fine
    return gdf.loc[mask].copy()


# ---------------------------------------------------------------------------
# Validazione e salvataggio
# ---------------------------------------------------------------------------


def riassumi(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Produce un riassunto di qualita' del dataset pulito."""
    riassunto = {
        "n_totali": int(len(gdf)),
        "n_per_anno": (
            gdf.groupby("anno", dropna=False).size().astype(int).to_dict()
            if "anno" in gdf.columns
            else {}
        ),
        "n_per_gravita": (
            gdf["gravita"].value_counts(dropna=False).astype(int).to_dict()
            if "gravita" in gdf.columns
            else {}
        ),
        "n_per_flag_qualita": (
            gdf["flag_qualita"].value_counts(dropna=False).astype(int).to_dict()
            if "flag_qualita" in gdf.columns
            else {}
        ),
        "n_da_rigeolocalizzare": int(gdf["da_rigeolocalizzare"].sum())
        if "da_rigeolocalizzare" in gdf.columns
        else 0,
    }
    return riassunto


def salva_geopackage(gdf: gpd.GeoDataFrame, percorso: Path) -> None:
    """Salva il GeoDataFrame in GeoPackage, creando la directory se serve."""
    percorso.parent.mkdir(parents=True, exist_ok=True)
    # Rimuove un eventuale file esistente per evitare conflitti di layer.
    if percorso.exists():
        percorso.unlink()
    log.info("Salvataggio GeoPackage: %s (%d record)", percorso, len(gdf))
    gdf.to_file(percorso, driver="GPKG", layer="incidenti_clean")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def pulisci(config: dict[str, Any]) -> gpd.GeoDataFrame:
    """Esegue l'intera pulizia e restituisce il GeoDataFrame risultante."""
    df = carica_incidenti_grezzi(config)
    df = standardizza_colonne(df)
    df = parsa_datetime(df)
    df = classifica_gravita(df)
    df = calcola_flag_qualita(df)

    crs_origine = config["crs"]["dato_incidenti"]
    crs_target = config["crs"]["metrico"]
    gdf = crea_geodataframe(df, crs_origine=crs_origine)
    gdf = riproietta(gdf, crs_target=crs_target)

    periodo = config.get("periodo_analisi", {})
    gdf = filtra_periodo(
        gdf,
        anno_inizio=periodo.get("anno_inizio"),
        anno_fine=periodo.get("anno_fine"),
    )
    return gdf


def main(config: dict[str, Any]) -> None:
    """Entry point dello step: esegue la pulizia e salva l'output."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    gdf = pulisci(config)

    riassunto = riassumi(gdf)
    log.info("Riassunto dataset pulito:")
    for chiave, valore in riassunto.items():
        log.info("  %s: %s", chiave, valore)

    output_rel = config["paths"]["interim"]["incidenti_clean"]
    output = RADICE_PROGETTO / output_rel
    salva_geopackage(gdf, output)


if __name__ == "__main__":
    main(carica_config())
