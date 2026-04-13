"""Caricamento centralizzato della configurazione del progetto.

Tutti gli script della pipeline (``s00`` ... ``s06``) devono leggere i propri
parametri tramite :func:`carica_config`, in modo che ``config.yaml`` resti
l'unica fonte di verita' per soglie, pesi e percorsi.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Radice del repository: due livelli sopra questo file (src/config.py).
RADICE_PROGETTO: Path = Path(__file__).resolve().parent.parent
PERCORSO_CONFIG_DEFAULT: Path = RADICE_PROGETTO / "config.yaml"


def carica_config(percorso: str | Path | None = None) -> dict[str, Any]:
    """Carica e restituisce il contenuto di ``config.yaml`` come dizionario.

    Parameters
    ----------
    percorso:
        Percorso al file YAML di configurazione. Se ``None`` viene usato
        ``<radice_progetto>/config.yaml``.

    Returns
    -------
    dict
        Dizionario con tutti i parametri di configurazione.
    """

    percorso_finale = Path(percorso) if percorso is not None else PERCORSO_CONFIG_DEFAULT
    with open(percorso_finale, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
