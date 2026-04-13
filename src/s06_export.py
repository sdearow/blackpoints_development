"""Step 06 - Export dei risultati per dashboard e reportistica (Fase 5/6).

Prepara i layer e le tabelle nei formati attesi dalla dashboard Dash
(GeoJSON/Parquet) e genera gli artefatti di reporting (schede sito PDF,
classifica Excel, mappa cittadina PNG, report di sintesi).

Output atteso: file in ``data/processed/`` e ``reports/``.
"""

from __future__ import annotations

from typing import Any

from src.config import carica_config


def main(config: dict[str, Any]) -> None:
    """Esporta i risultati per dashboard e reporting.

    TODO: implementare (Fase 5/6, Task 5.5 e 6.x).
    """

    raise NotImplementedError(
        "s06_export: da implementare (Fase 5/6)."
    )


if __name__ == "__main__":
    main(carica_config())
