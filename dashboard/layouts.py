"""Layout Dash della dashboard Black Point Roma.

Cinque tab principali:
1. Mappa: segmenti e intersezioni colorati per fascia di priorita'
2. Analisi SPF: scatter O vs E, diagnostica modelli
3. Analisi EB: distribuzioni eccesso, top siti
4. Sensitivita' pesi: slider pesi ICP, confronto ranking
5. Vista decisionale: matrice di rischio, classifica top-N
"""

from __future__ import annotations

from dash import dash_table, dcc, html

COLORI_FASCE = {
    "monitoraggio": "#2ecc71",
    "bassa": "#f1c40f",
    "media": "#e67e22",
    "alta": "#e74c3c",
    "altissima": "#8b0000",
}

ORDINE_FASCE = ["monitoraggio", "bassa", "media", "alta", "altissima"]

STILE_CARD = {
    "backgroundColor": "#1e1e2e",
    "borderRadius": "8px",
    "padding": "16px",
    "marginBottom": "12px",
}

STILE_TITOLO_CARD = {
    "color": "#cdd6f4",
    "fontSize": "13px",
    "fontWeight": "600",
    "textTransform": "uppercase",
    "letterSpacing": "0.05em",
    "marginBottom": "10px",
}


def _legenda_fasce() -> html.Div:
    items = []
    for fascia in ORDINE_FASCE:
        items.append(
            html.Div(
                [
                    html.Span(
                        style={
                            "display": "inline-block",
                            "width": "12px",
                            "height": "12px",
                            "borderRadius": "50%",
                            "backgroundColor": COLORI_FASCE[fascia],
                            "marginRight": "6px",
                        }
                    ),
                    html.Span(fascia.capitalize(), style={"color": "#cdd6f4", "fontSize": "12px"}),
                ],
                style={"display": "flex", "alignItems": "center", "marginBottom": "4px"},
            )
        )
    return html.Div(items)


def _pannello_filtri() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.P("Tipo sito", style=STILE_TITOLO_CARD),
                    dcc.Checklist(
                        id="filtro-tipo",
                        options=[
                            {"label": " Segmenti", "value": "segmento"},
                            {"label": " Intersezioni", "value": "intersezione"},
                        ],
                        value=["segmento", "intersezione"],
                        labelStyle={"display": "block", "color": "#cdd6f4", "fontSize": "13px"},
                        inputStyle={"marginRight": "6px"},
                    ),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Intersezioni", style=STILE_TITOLO_CARD),
                    dcc.RadioItems(
                        id="filtro-intersezioni",
                        options=[
                            {"label": " Tutte", "value": "tutte"},
                            {"label": " Semaforizzate", "value": "semaforizzata"},
                            {"label": " Non semaforizzate", "value": "non_semaforizzata"},
                        ],
                        value="tutte",
                        labelStyle={"display": "block", "color": "#cdd6f4", "fontSize": "13px"},
                        inputStyle={"marginRight": "6px"},
                    ),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Rete", style=STILE_TITOLO_CARD),
                    dcc.RadioItems(
                        id="filtro-hin",
                        options=[
                            {"label": " Tutta la rete", "value": "tutta"},
                            {"label": " Solo HIN", "value": "hin"},
                        ],
                        value="tutta",
                        labelStyle={"display": "block", "color": "#cdd6f4", "fontSize": "13px"},
                        inputStyle={"marginRight": "6px"},
                    ),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Fascia priorita'", style=STILE_TITOLO_CARD),
                    dcc.Checklist(
                        id="filtro-fascia",
                        options=[{"label": f" {f.capitalize()}", "value": f} for f in ORDINE_FASCE],
                        value=ORDINE_FASCE,
                        labelStyle={"display": "block", "color": "#cdd6f4", "fontSize": "13px"},
                        inputStyle={"marginRight": "6px"},
                    ),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Ordina per", style=STILE_TITOLO_CARD),
                    dcc.RadioItems(
                        id="filtro-metrica",
                        options=[
                            {"label": " ICP", "value": "ICP"},
                            {"label": " N. incidenti", "value": "n_incidenti"},
                            {"label": " Eccesso EPDO", "value": "excess_EPDO_i"},
                            {"label": " KSI/km", "value": "ksi_km"},
                            {"label": " Hotspot NKDE", "value": "nkde_max"},
                        ],
                        value="ICP",
                        labelStyle={"display": "block", "color": "#cdd6f4", "fontSize": "13px"},
                        inputStyle={"marginRight": "6px"},
                    ),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Mostra top N", style=STILE_TITOLO_CARD),
                    dcc.Slider(
                        id="slider-top-n",
                        min=50,
                        max=5000,
                        step=50,
                        value=500,
                        marks={50: "50", 250: "250", 500: "500", 1000: "1k", 2500: "2.5k", 5000: "5k"},
                        tooltip={"placement": "bottom", "always_visible": True},
                    ),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Legenda", style=STILE_TITOLO_CARD),
                    _legenda_fasce(),
                ],
                style=STILE_CARD,
            ),
        ],
        style={"width": "220px", "flexShrink": "0"},
    )


def _pannello_mappa() -> html.Div:
    return html.Div(
        [
            dcc.Graph(
                id="mappa-principale",
                style={"height": "calc(100vh - 100px)"},
                config={"scrollZoom": True, "displayModeBar": True},
            ),
        ],
        style={"flex": "1", "minWidth": "0"},
    )


def _pannello_dettaglio() -> html.Div:
    return html.Div(
        [
            html.Div(
                id="dettaglio-header",
                children=[
                    html.P(
                        "Seleziona un sito sulla mappa per vedere il dettaglio.",
                        style={"color": "#6c7086", "fontStyle": "italic", "fontSize": "14px"},
                    )
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Componenti ICP (normalizzate 0-100)", style=STILE_TITOLO_CARD),
                    dcc.Graph(id="radar-componenti", style={"height": "260px"},
                              config={"displayModeBar": False}),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Incidenti per gravita'", style=STILE_TITOLO_CARD),
                    dcc.Graph(id="bar-gravita", style={"height": "180px"},
                              config={"displayModeBar": False}),
                ],
                style=STILE_CARD,
            ),
        ],
        style={"width": "340px", "flexShrink": "0", "overflowY": "auto",
               "maxHeight": "calc(100vh - 100px)"},
    )


def tab_mappa() -> html.Div:
    return html.Div(
        [
            _pannello_filtri(),
            _pannello_mappa(),
            _pannello_dettaglio(),
        ],
        style={"display": "flex", "gap": "12px", "padding": "12px",
               "backgroundColor": "#181825"},
    )


# =====================================================================
# Tab 2 — Analisi SPF
# =====================================================================

def tab_spf() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.P("Filtro tipo sito", style=STILE_TITOLO_CARD),
                            dcc.RadioItems(
                                id="spf-tipo-sito",
                                options=[
                                    {"label": " Segmenti", "value": "segmento"},
                                    {"label": " Intersezioni", "value": "intersezione"},
                                ],
                                value="segmento",
                                labelStyle={"display": "inline-block", "color": "#cdd6f4",
                                            "fontSize": "13px", "marginRight": "16px"},
                                inputStyle={"marginRight": "6px"},
                            ),
                        ],
                        style={**STILE_CARD, "display": "inline-block"},
                    ),
                    html.Div(
                        [
                            html.P("Filtro categoria SPF", style=STILE_TITOLO_CARD),
                            dcc.Dropdown(
                                id="spf-categoria",
                                placeholder="Tutte le categorie",
                                multi=True,
                                style={"backgroundColor": "#313244", "color": "#cdd6f4"},
                            ),
                        ],
                        style={**STILE_CARD, "display": "inline-block", "minWidth": "300px",
                               "marginLeft": "12px"},
                    ),
                ],
                style={"display": "flex", "alignItems": "flex-start", "flexWrap": "wrap"},
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.P("Osservati vs Predetti SPF (binned)", style=STILE_TITOLO_CARD),
                            dcc.Graph(id="spf-scatter-oe", style={"height": "420px"},
                                      config={"displayModeBar": True}),
                        ],
                        style={**STILE_CARD, "flex": "1"},
                    ),
                    html.Div(
                        [
                            html.P("Distribuzione residui di Pearson", style=STILE_TITOLO_CARD),
                            dcc.Graph(id="spf-residui", style={"height": "420px"},
                                      config={"displayModeBar": True}),
                        ],
                        style={**STILE_CARD, "flex": "1"},
                    ),
                ],
                style={"display": "flex", "gap": "12px"},
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.P("Distribuzione incidenti per sito", style=STILE_TITOLO_CARD),
                            dcc.Graph(id="spf-hist-incidenti", style={"height": "350px"},
                                      config={"displayModeBar": True}),
                        ],
                        style={**STILE_CARD, "flex": "1"},
                    ),
                    html.Div(
                        [
                            html.P("Riepilogo modelli SPF", style=STILE_TITOLO_CARD),
                            html.Div(id="spf-riepilogo-modelli"),
                        ],
                        style={**STILE_CARD, "flex": "1", "overflowX": "auto"},
                    ),
                ],
                style={"display": "flex", "gap": "12px"},
            ),
        ],
        style={"padding": "12px", "backgroundColor": "#181825"},
    )


# =====================================================================
# Tab 3 — Analisi EB
# =====================================================================

def tab_eb() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.P("Filtro tipo sito", style=STILE_TITOLO_CARD),
                    dcc.RadioItems(
                        id="eb-tipo-sito",
                        options=[
                            {"label": " Segmenti", "value": "segmento"},
                            {"label": " Intersezioni", "value": "intersezione"},
                        ],
                        value="segmento",
                        labelStyle={"display": "inline-block", "color": "#cdd6f4",
                                    "fontSize": "13px", "marginRight": "16px"},
                        inputStyle={"marginRight": "6px"},
                    ),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.P("Distribuzione excess_i (EB - SPF)", style=STILE_TITOLO_CARD),
                            dcc.Graph(id="eb-hist-excess", style={"height": "380px"},
                                      config={"displayModeBar": True}),
                        ],
                        style={**STILE_CARD, "flex": "1"},
                    ),
                    html.Div(
                        [
                            html.P("Distribuzione excess EPDO", style=STILE_TITOLO_CARD),
                            dcc.Graph(id="eb-hist-epdo", style={"height": "380px"},
                                      config={"displayModeBar": True}),
                        ],
                        style={**STILE_CARD, "flex": "1"},
                    ),
                ],
                style={"display": "flex", "gap": "12px"},
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.P("Peso EB (w_i) vs n_incidenti", style=STILE_TITOLO_CARD),
                            dcc.Graph(id="eb-scatter-peso", style={"height": "380px"},
                                      config={"displayModeBar": True}),
                        ],
                        style={**STILE_CARD, "flex": "1"},
                    ),
                    html.Div(
                        [
                            html.P("Top 30 siti per eccesso EPDO", style=STILE_TITOLO_CARD),
                            dash_table.DataTable(
                                id="eb-tabella-top",
                                page_size=15,
                                sort_action="native",
                                style_header={
                                    "backgroundColor": "#313244",
                                    "color": "#cdd6f4",
                                    "fontWeight": "600",
                                    "fontSize": "11px",
                                    "border": "none",
                                },
                                style_cell={
                                    "backgroundColor": "#1e1e2e",
                                    "color": "#cdd6f4",
                                    "fontSize": "11px",
                                    "border": "1px solid #313244",
                                    "padding": "4px 8px",
                                },
                            ),
                        ],
                        style={**STILE_CARD, "flex": "1"},
                    ),
                ],
                style={"display": "flex", "gap": "12px"},
            ),
        ],
        style={"padding": "12px", "backgroundColor": "#181825"},
    )


# =====================================================================
# Tab 4 — Sensitivita' pesi
# =====================================================================

def _slider_peso(id_slider: str, label: str, valore: float) -> html.Div:
    return html.Div(
        [
            html.Label(label, style={"color": "#cdd6f4", "fontSize": "13px",
                                     "fontWeight": "600", "marginBottom": "4px"}),
            dcc.Slider(
                id=id_slider,
                min=0, max=100, step=5,
                value=int(valore * 100),
                marks={0: "0", 25: "25", 50: "50", 75: "75", 100: "100"},
                tooltip={"placement": "bottom", "always_visible": True},
            ),
        ],
        style={"marginBottom": "16px"},
    )


def tab_sensitivita() -> html.Div:
    # --- Colonna sinistra: ranking con pesi default (solo Eccesso EPDO) ---
    colonna_sinistra = html.Div(
        [
            html.Div(
                [
                    html.P("Filtri", style=STILE_TITOLO_CARD),
                    html.Label("Categoria stradale (segmenti)",
                               style={"color": "#cdd6f4", "fontSize": "12px",
                                      "fontWeight": "600"}),
                    dcc.Dropdown(
                        id="sens-filtro-categoria",
                        placeholder="Tutte le categorie",
                        multi=True,
                        style={"backgroundColor": "#313244", "color": "#cdd6f4",
                               "marginBottom": "12px", "marginTop": "4px"},
                    ),
                    html.Label("Tipo intersezione",
                               style={"color": "#cdd6f4", "fontSize": "12px",
                                      "fontWeight": "600"}),
                    dcc.RadioItems(
                        id="sens-filtro-int",
                        options=[
                            {"label": " Tutte", "value": "tutte"},
                            {"label": " Semaforizzate", "value": "semaforizzata"},
                            {"label": " Non semaforizzate", "value": "non_semaforizzata"},
                        ],
                        value="tutte",
                        labelStyle={"display": "block", "color": "#cdd6f4",
                                    "fontSize": "13px"},
                        inputStyle={"marginRight": "6px"},
                        style={"marginTop": "4px"},
                    ),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Ranking segmenti — pesi default (solo Eccesso EPDO)",
                           style=STILE_TITOLO_CARD),
                    html.Div(id="sens-rank-seg-default"),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Ranking intersezioni — pesi default (solo Eccesso EPDO)",
                           style=STILE_TITOLO_CARD),
                    html.Div(id="sens-rank-int-default"),
                ],
                style=STILE_CARD,
            ),
        ],
        style={"flex": "1", "minWidth": "0"},
    )

    # --- Colonna destra: ranking con pesi personalizzati ---
    colonna_destra = html.Div(
        [
            html.Div(
                [
                    html.P("Pesi ICP personalizzati (normalizzati a somma = 1)",
                           style=STILE_TITOLO_CARD),
                    _slider_peso("peso-A", "A — Eccesso EB-EPDO", 1.00),
                    _slider_peso("peso-B", "B — Severita'", 0.00),
                    _slider_peso("peso-C", "C — Vulnerabilita' pedoni", 0.00),
                    _slider_peso("peso-D", "D — Dispersione velocita'", 0.00),
                    html.Div(id="pesi-normalizzati",
                             style={"color": "#a6adc8", "fontSize": "12px",
                                    "marginTop": "8px"}),
                    html.Div(
                        [
                            html.Span("Spearman rho vs default — ",
                                      style={"color": "#a6adc8", "fontSize": "12px"}),
                            html.Span(id="sens-rho-seg",
                                      style={"fontSize": "12px", "fontWeight": "700"}),
                            html.Span(id="sens-rho-int",
                                      style={"fontSize": "12px", "fontWeight": "700",
                                             "marginLeft": "12px"}),
                        ],
                        style={"marginTop": "10px"},
                    ),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Ranking segmenti — pesi personalizzati",
                           style=STILE_TITOLO_CARD),
                    html.Div(id="sens-rank-seg-nuovo"),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Ranking intersezioni — pesi personalizzati",
                           style=STILE_TITOLO_CARD),
                    html.Div(id="sens-rank-int-nuovo"),
                ],
                style=STILE_CARD,
            ),
        ],
        style={"flex": "1", "minWidth": "0"},
    )

    return html.Div(
        [colonna_sinistra, colonna_destra],
        style={"display": "flex", "gap": "12px",
               "padding": "12px", "backgroundColor": "#181825"},
    )


# =====================================================================
# Tab 5 — Vista decisionale
# =====================================================================

def tab_decisionale() -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.P("Matrice di rischio (eccesso EB x severita')", style=STILE_TITOLO_CARD),
                            dcc.Graph(id="scatter-matrice", style={"height": "450px"},
                                      config={"displayModeBar": True}),
                        ],
                        style={**STILE_CARD, "flex": "1"},
                    ),
                    html.Div(
                        [
                            html.P("Distribuzione per fascia", style=STILE_TITOLO_CARD),
                            dcc.Graph(id="bar-fasce", style={"height": "450px"},
                                      config={"displayModeBar": False}),
                        ],
                        style={**STILE_CARD, "width": "300px", "flexShrink": "0"},
                    ),
                ],
                style={"display": "flex", "gap": "12px"},
            ),
            html.Div(
                [
                    html.P("Filtro categoria per classifica", style=STILE_TITOLO_CARD),
                    dcc.Dropdown(
                        id="dec-filtro-categoria",
                        placeholder="Tutte le categorie (classifica globale)",
                        multi=True,
                        style={"backgroundColor": "#313244", "color": "#cdd6f4"},
                    ),
                ],
                style={**STILE_CARD, "maxWidth": "500px"},
            ),
            html.Div(
                [
                    html.P("Top 50 siti per ICP", style=STILE_TITOLO_CARD),
                    dash_table.DataTable(
                        id="tabella-top",
                        page_size=20,
                        sort_action="native",
                        filter_action="native",
                        style_header={
                            "backgroundColor": "#313244",
                            "color": "#cdd6f4",
                            "fontWeight": "600",
                            "fontSize": "12px",
                            "border": "none",
                        },
                        style_cell={
                            "backgroundColor": "#1e1e2e",
                            "color": "#cdd6f4",
                            "fontSize": "12px",
                            "border": "1px solid #313244",
                            "padding": "6px 10px",
                        },
                        style_data_conditional=[
                            {"if": {"filter_query": '{fascia_priorita} = "altissima"'},
                             "backgroundColor": "#3b0000", "color": "#ff8080"},
                            {"if": {"filter_query": '{fascia_priorita} = "alta"'},
                             "backgroundColor": "#3b1a1a"},
                        ],
                    ),
                ],
                style=STILE_CARD,
            ),
        ],
        style={"padding": "12px", "backgroundColor": "#181825"},
    )


# =====================================================================
# Layout principale
# =====================================================================

def costruisci_layout() -> html.Div:
    tab_style = {"color": "#6c7086", "backgroundColor": "#181825",
                 "border": "none", "padding": "6px 16px"}
    tab_selected = {"color": "#cdd6f4", "backgroundColor": "#313244",
                    "border": "none", "padding": "6px 16px"}
    return html.Div(
        [
            html.Div(
                [
                    html.H1(
                        "Black Point Roma",
                        style={"color": "#cdd6f4", "fontSize": "18px",
                               "margin": "0", "fontWeight": "700"},
                    ),
                    html.Span(
                        "Sistema di identificazione dei siti ad alta incidentalita'",
                        style={"color": "#6c7086", "fontSize": "12px"},
                    ),
                    html.Div(
                        dcc.Tabs(
                            id="tabs-principale",
                            value="mappa",
                            children=[
                                dcc.Tab(label="Mappa", value="mappa",
                                        style=tab_style, selected_style=tab_selected),
                                dcc.Tab(label="Analisi SPF", value="spf",
                                        style=tab_style, selected_style=tab_selected),
                                dcc.Tab(label="Analisi EB", value="eb",
                                        style=tab_style, selected_style=tab_selected),
                                dcc.Tab(label="Sensitivita' pesi", value="sensitivita",
                                        style=tab_style, selected_style=tab_selected),
                                dcc.Tab(label="Equita'", value="equita",
                                        style=tab_style, selected_style=tab_selected),
                                dcc.Tab(label="Vista decisionale", value="decisionale",
                                        style=tab_style, selected_style=tab_selected),
                            ],
                        ),
                        style={"marginLeft": "auto"},
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "16px",
                    "padding": "10px 16px",
                    "backgroundColor": "#11111b",
                    "borderBottom": "1px solid #313244",
                },
            ),
            html.Div(id="contenuto-tab"),
            dcc.Store(id="sito-selezionato"),
            dcc.Store(id="pesi-correnti",
                      data={"A": 100, "B": 0, "C": 0, "D": 0}),
        ],
        style={"fontFamily": "'Inter', 'Segoe UI', sans-serif",
               "backgroundColor": "#181825", "minHeight": "100vh"},
    )


# ---------------------------------------------------------------------------
# Tab Equita' (Modulo B del PSS)
# ---------------------------------------------------------------------------

# Palette bivariata 3x3 (Stevens purple-blue): righe = bisogno (1=basso,
# 3=alto), colonne = dotazione (1=bassa, 3=alta). "3-1" = alto bisogno e
# bassa dotazione -> il mismatch da evidenziare.
COLORI_BIVARIATA = {
    "1-1": "#e8e8e8", "1-2": "#ace4e4", "1-3": "#5ac8c8",
    "2-1": "#dfb0d6", "2-2": "#a5add3", "2-3": "#5698b9",
    "3-1": "#be64ac", "3-2": "#8c62aa", "3-3": "#3b4994",
}


def _legenda_bivariata() -> html.Div:
    """Griglia 3x3 della choropleth bivariata (bisogno x dotazione)."""
    righe = []
    for b in (3, 2, 1):  # bisogno alto in alto
        celle = []
        for d in (1, 2, 3):
            celle.append(html.Div(style={
                "width": "22px", "height": "22px",
                "backgroundColor": COLORI_BIVARIATA[f"{b}-{d}"],
                "outline": "2px solid #f38ba8" if (b, d) == (3, 1) else "none",
            }))
        righe.append(html.Div(celle, style={"display": "flex", "gap": "2px",
                                            "marginBottom": "2px"}))
    return html.Div(
        [
            html.Div(righe),
            html.Div("dotazione →", style={"color": "#6c7086", "fontSize": "10px"}),
            html.Div("↑ bisogno", style={"color": "#6c7086", "fontSize": "10px"}),
            html.Div("bordo rosa = zona prioritaria (3-1)",
                     style={"color": "#f38ba8", "fontSize": "10px",
                            "marginTop": "4px"}),
        ]
    )


def tab_equita() -> html.Div:
    pannello_controlli = html.Div(
        [
            html.Div(
                [
                    html.P("Vista mappa", style=STILE_TITOLO_CARD),
                    dcc.RadioItems(
                        id="equita-vista",
                        options=[
                            {"label": " Bivariata bisogno x dotazione", "value": "bivariata"},
                            {"label": " Bisogno", "value": "bisogno"},
                            {"label": " Vulnerabilita' sociale", "value": "vulnerabilita"},
                            {"label": " Dotazione interventi", "value": "dotazione"},
                            {"label": " Equity priority zones", "value": "priority"},
                            {"label": " Cluster LISA", "value": "lisa"},
                        ],
                        value="bivariata",
                        labelStyle={"display": "block", "color": "#cdd6f4", "fontSize": "13px"},
                        inputStyle={"marginRight": "6px"},
                    ),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Tipologia interventi", style=STILE_TITOLO_CARD),
                    dcc.Dropdown(
                        id="equita-tipo",
                        options=[],   # popolato dal callback
                        value="dot_totale",
                        clearable=False,
                        style={"fontSize": "12px"},
                    ),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Legenda bivariata", style=STILE_TITOLO_CARD),
                    _legenda_bivariata(),
                ],
                style=STILE_CARD,
            ),
            html.Div(id="equita-indici", style=STILE_CARD),
        ],
        style={"width": "250px", "flexShrink": "0"},
    )

    pannello_grafici = html.Div(
        [
            html.Div(
                [
                    html.P("Curva di Lorenz della dotazione", style=STILE_TITOLO_CARD),
                    dcc.Graph(id="equita-lorenz", style={"height": "260px"},
                              config={"displayModeBar": False}),
                ],
                style=STILE_CARD,
            ),
            html.Div(
                [
                    html.P("Sensibilita' (concentration index per schema di pesi)",
                           style=STILE_TITOLO_CARD),
                    html.Div(id="equita-sensibilita"),
                ],
                style=STILE_CARD,
            ),
        ],
        style={"width": "320px", "flexShrink": "0"},
    )

    return html.Div(
        [
            pannello_controlli,
            html.Div(
                dcc.Graph(
                    id="equita-mappa",
                    style={"height": "calc(100vh - 100px)"},
                    config={"scrollZoom": True},
                ),
                style={"flexGrow": "1"},
            ),
            pannello_grafici,
        ],
        style={"display": "flex", "gap": "12px", "padding": "12px"},
    )
