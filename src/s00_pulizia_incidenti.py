"""Step 00 - Pulizia del database incidenti (Fase 0, Task 0.1).

Importa il dataset grezzo degli incidenti, standardizza i campi (coordinate,
gravita', data/ora, tipi veicolo, toponomastica), filtra le annualita' di
interesse e calcola un flag di affidabilita' della geocodifica.

Output atteso: GeoDataFrame ``incidenti_clean`` salvato in
``data/interim/incidenti_clean.gpkg``.
"""

from __future__ import annotations

from typing import Any

from src.config import carica_config


def main(config: dict[str, Any]) -> None:
    """Esegue la pulizia del database incidenti.

    TODO: implementare nello step successivo (Task 0.1 del piano).
    """

    raise NotImplementedError(
        "s00_pulizia_incidenti: da implementare nello step successivo (Task 0.1)."
    )


if __name__ == "__main__":
    main(carica_config())
