"""Callback Dash per interattivita' (filtri, click sui siti, grafici).

Registra tutti i callback dell'applicazione tramite la funzione
`registra_callbacks(app, df)`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, html
from dash.exceptions import PreventUpdate

from dashboard.layouts import COLORI_FASCE, ORDINE_FASCE

_SFONDO = "#1e1e2e"
_TESTO = "#cdd6f4"
_GRIGLIA = "#313244"

_LAYOUT_BASE = dict(
    paper_bgcolor=_SFONDO,
    plot_bgcolor=_SFONDO,
    font_color=_TESTO,
    margin=dict(l=40, r=20, t=20, b=40),
)


def _figura_vuota(messaggio: str = "") -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        **_LAYOUT_BASE,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[dict(text=messaggio, showarrow=False,
                          font=dict(color="#6c7086", size=13))],
    )
    return fig


def registra_callbacks(app: Any, df: pd.DataFrame) -> None:
    """Registra tutti i callback dell'applicazione.

    Parameters
    ----------
    app : Dash
        Istanza dell'applicazione Dash.
    df : pd.DataFrame
        DataFrame unificato (segmenti + intersezioni) con colonne lon, lat,
        ICP, fascia_priorita, tipo_sito e le componenti.
    """
    from dashboard.layouts import tab_decisionale, tab_mappa

    # ------------------------------------------------------------------
    # Callback 1: switch tab
    # ------------------------------------------------------------------
    @app.callback(
        Output("contenuto-tab", "children"),
        Input("tabs-principale", "value"),
    )
    def cambia_tab(valore: str) -> Any:
        if valore == "mappa":
            return tab_mappa()
        return tab_decisionale()

    # ------------------------------------------------------------------
    # Callback 2: aggiorna mappa principale
    # ------------------------------------------------------------------
    @app.callback(
        Output("mappa-principale", "figure"),
        Input("filtro-tipo", "value"),
        Input("filtro-fascia", "value"),
        Input("slider-top-n", "value"),
    )
    def aggiorna_mappa(
        tipi: list[str],
        fasce: list[str],
        top_n: int,
    ) -> go.Figure:
        mask = df["tipo_sito"].isin(tipi or []) & df["fascia_priorita"].isin(fasce or [])
        sub = df.loc[mask].nlargest(top_n, "ICP")

        fig = go.Figure()
        for fascia in ORDINE_FASCE:
            if fascia not in (fasce or []):
                continue
            per_fascia = sub[sub["fascia_priorita"] == fascia]
            if per_fascia.empty:
                continue

            seg = per_fascia[per_fascia["tipo_sito"] == "segmento"]
            if not seg.empty and "segmento" in (tipi or []):
                fig.add_trace(
                    go.Scattermap(
                        lat=seg["lat"],
                        lon=seg["lon"],
                        mode="markers",
                        marker=dict(size=6, color=COLORI_FASCE[fascia], opacity=0.8),
                        text=seg.apply(
                            lambda r: f"<b>{r.get('toponimo', 'Segmento')}</b><br>"
                                      f"ICP: {r['ICP']:.1f} | Fascia: {fascia}<br>"
                                      f"Incidenti: {int(r.get('n_incidenti', 0))}",
                            axis=1,
                        ),
                        hoverinfo="text",
                        name=f"Seg. {fascia}",
                        customdata=seg.index,
                    )
                )
            inter = per_fascia[per_fascia["tipo_sito"] == "intersezione"]
            if not inter.empty and "intersezione" in (tipi or []):
                fig.add_trace(
                    go.Scattermap(
                        lat=inter["lat"],
                        lon=inter["lon"],
                        mode="markers",
                        marker=dict(size=8, color=COLORI_FASCE[fascia],
                                    symbol="circle", opacity=0.9,
                                    line=dict(width=1, color="#11111b")),
                        text=inter.apply(
                            lambda r: f"<b>Intersezione #{int(r.get('id_nodo', 0))}</b><br>"
                                      f"ICP: {r['ICP']:.1f} | Fascia: {fascia}<br>"
                                      f"Incidenti: {int(r.get('n_incidenti', 0))}",
                            axis=1,
                        ),
                        hoverinfo="text",
                        name=f"Int. {fascia}",
                        customdata=inter.index,
                    )
                )

        fig.update_layout(
            **_LAYOUT_BASE,
            map=dict(
                style="open-street-map",
                center=dict(lat=41.9028, lon=12.4964),
                zoom=11,
            ),
            margin=dict(l=0, r=0, t=0, b=0),
            legend=dict(
                bgcolor="#11111b", font=dict(color=_TESTO, size=10),
                x=0.01, y=0.99, xanchor="left", yanchor="top",
            ),
            showlegend=True,
            uirevision="mappa",
        )
        return fig

    # ------------------------------------------------------------------
    # Callback 3: salva sito selezionato dallo store al click sulla mappa
    # ------------------------------------------------------------------
    @app.callback(
        Output("sito-selezionato", "data"),
        Input("mappa-principale", "clickData"),
    )
    def aggiorna_sito_selezionato(click_data: dict | None) -> dict | None:
        if not click_data:
            raise PreventUpdate
        punto = click_data["points"][0]
        idx = punto.get("customdata")
        if idx is None:
            raise PreventUpdate
        riga = df.loc[idx]
        return riga.to_dict()

    # ------------------------------------------------------------------
    # Callback 4: pannello dettaglio (header + radar + barre gravita')
    # ------------------------------------------------------------------
    @app.callback(
        Output("dettaglio-header", "children"),
        Output("radar-componenti", "figure"),
        Output("bar-gravita", "figure"),
        Input("sito-selezionato", "data"),
    )
    def aggiorna_dettaglio(sito: dict | None) -> tuple:
        if not sito:
            vuoto = _figura_vuota("Nessun sito selezionato")
            placeholder = [
                _msg_placeholder("Seleziona un sito sulla mappa.")
            ]
            return placeholder, vuoto, vuoto

        fascia = sito.get("fascia_priorita", "")
        colore_fascia = COLORI_FASCE.get(fascia, "#cdd6f4")
        nome = sito.get("toponimo") or f"Intersezione #{sito.get('id_nodo', '')}"
        icp = sito.get("ICP", 0.0)
        tipo = sito.get("tipo_sito", "")

        header = [
            html.Div(
                [
                    html.Span(
                        fascia.upper(),
                        style={"backgroundColor": colore_fascia, "color": "#11111b",
                               "borderRadius": "4px", "padding": "2px 8px",
                               "fontSize": "11px", "fontWeight": "700"},
                    ),
                    html.Span(
                        f"  ICP: {icp:.1f}",
                        style={"color": _TESTO, "fontSize": "13px", "marginLeft": "8px"},
                    ),
                ],
                style={"marginBottom": "8px"},
            ),
            html.P(nome, style={"color": _TESTO, "fontWeight": "600",
                                "fontSize": "14px", "margin": "0"}),
            html.P(
                f"{tipo.capitalize()} | "
                f"Incidenti: {int(sito.get('n_incidenti', 0))} | "
                f"Costo eccesso: €{sito.get('costo_sociale_eccesso_eur', 0):,.0f}",
                style={"color": "#6c7086", "fontSize": "12px", "margin": "4px 0 0 0"},
            ),
        ]

        # Radar chart componenti.
        comp_val = [
            sito.get("A_norm", 0),
            sito.get("B_norm", 0),
            sito.get("C_norm", 0),
            sito.get("D_norm", 0),
        ]
        comp_lab = ["Eccesso EB", "Severita'", "Vulnerabilita'", "Vel. rischio"]
        fig_radar = go.Figure()
        fig_radar.add_trace(
            go.Scatterpolar(
                r=comp_val + [comp_val[0]],
                theta=comp_lab + [comp_lab[0]],
                fill="toself",
                fillcolor=f"rgba(231,76,60,0.25)",
                line=dict(color="#e74c3c", width=2),
                name="Sito",
            )
        )
        fig_radar.add_trace(
            go.Scatterpolar(
                r=[50, 50, 50, 50, 50],
                theta=comp_lab + [comp_lab[0]],
                line=dict(color="#6c7086", width=1, dash="dot"),
                name="Media rete",
            )
        )
        fig_radar.update_layout(
            **_LAYOUT_BASE,
            polar=dict(
                bgcolor=_SFONDO,
                radialaxis=dict(range=[0, 100], gridcolor=_GRIGLIA,
                                tickfont=dict(size=9, color="#6c7086")),
                angularaxis=dict(gridcolor=_GRIGLIA,
                                 tickfont=dict(size=10, color=_TESTO)),
            ),
            showlegend=True,
            legend=dict(font=dict(size=9, color=_TESTO), bgcolor=_SFONDO),
            margin=dict(l=30, r=30, t=20, b=20),
        )

        # Barre gravita'.
        gravita = {
            "Mortali": int(sito.get("n_mortali", 0)),
            "Feriti gravi": int(sito.get("n_feriti_gravi", 0)),
            "Feriti lievi": int(sito.get("n_feriti_lievi", 0)),
            "Solo danni": int(sito.get("n_solo_danni", 0)),
        }
        fig_bar = go.Figure(
            go.Bar(
                x=list(gravita.values()),
                y=list(gravita.keys()),
                orientation="h",
                marker_color=["#8b0000", "#e74c3c", "#e67e22", "#f1c40f"],
            )
        )
        fig_bar.update_layout(
            **_LAYOUT_BASE,
            xaxis=dict(gridcolor=_GRIGLIA, tickfont=dict(size=10)),
            yaxis=dict(tickfont=dict(size=10)),
            margin=dict(l=80, r=20, t=10, b=30),
        )
        return header, fig_radar, fig_bar

    # ------------------------------------------------------------------
    # Callback 5: matrice di rischio e bar fasce (tab decisionale)
    # ------------------------------------------------------------------
    @app.callback(
        Output("scatter-matrice", "figure"),
        Output("bar-fasce", "figure"),
        Output("tabella-top", "data"),
        Output("tabella-top", "columns"),
        Input("tabs-principale", "value"),
    )
    def aggiorna_decisionale(tab: str) -> tuple:
        if tab != "decisionale":
            raise PreventUpdate

        # Scatter matrice di rischio.
        fig_scatter = go.Figure()
        for fascia in ORDINE_FASCE:
            sub = df[df["fascia_priorita"] == fascia]
            if sub.empty:
                continue
            fig_scatter.add_trace(
                go.Scatter(
                    x=sub["excess_EPDO_i"].clip(lower=-50),
                    y=sub["B_norm"],
                    mode="markers",
                    marker=dict(size=4, color=COLORI_FASCE[fascia], opacity=0.6),
                    name=fascia.capitalize(),
                    text=sub.apply(
                        lambda r: f"ICP: {r['ICP']:.1f}", axis=1
                    ),
                    hoverinfo="text",
                )
            )
        fig_scatter.update_layout(
            **_LAYOUT_BASE,
            xaxis=dict(title="Eccesso EPDO", gridcolor=_GRIGLIA, zeroline=True,
                       zerolinecolor="#6c7086"),
            yaxis=dict(title="Severita' (norm.)", gridcolor=_GRIGLIA, zeroline=True,
                       zerolinecolor="#6c7086"),
            legend=dict(bgcolor=_SFONDO, font=dict(size=10, color=_TESTO)),
        )

        # Bar fasce per tipo sito.
        conteggi_seg = (
            df[df["tipo_sito"] == "segmento"]["fascia_priorita"]
            .value_counts()
            .reindex(ORDINE_FASCE, fill_value=0)
        )
        conteggi_int = (
            df[df["tipo_sito"] == "intersezione"]["fascia_priorita"]
            .value_counts()
            .reindex(ORDINE_FASCE, fill_value=0)
        )
        fig_bar = go.Figure(
            [
                go.Bar(name="Segmenti", x=ORDINE_FASCE,
                       y=conteggi_seg.values,
                       marker_color=[COLORI_FASCE[f] for f in ORDINE_FASCE],
                       opacity=0.85),
                go.Bar(name="Intersezioni", x=ORDINE_FASCE,
                       y=conteggi_int.values,
                       marker_color=[COLORI_FASCE[f] for f in ORDINE_FASCE],
                       opacity=0.5),
            ]
        )
        fig_bar.update_layout(
            **_LAYOUT_BASE,
            barmode="group",
            xaxis=dict(tickfont=dict(size=10)),
            yaxis=dict(gridcolor=_GRIGLIA, tickfont=dict(size=10)),
            legend=dict(bgcolor=_SFONDO, font=dict(size=10, color=_TESTO)),
        )

        # Top 50 siti.
        cols_tab = ["tipo_sito", "toponimo", "fascia_priorita", "ICP",
                    "A_norm", "B_norm", "C_norm", "D_norm",
                    "n_incidenti", "costo_sociale_eccesso_eur"]
        cols_tab = [c for c in cols_tab if c in df.columns]
        top50 = (
            df.nlargest(50, "ICP")[cols_tab]
            .round(2)
            .to_dict("records")
        )
        columns = [{"name": c, "id": c} for c in cols_tab]
        return fig_scatter, fig_bar, top50, columns


def _msg_placeholder(testo: str) -> Any:
    return html.P(testo, style={"color": "#6c7086", "fontStyle": "italic", "fontSize": "14px"})
