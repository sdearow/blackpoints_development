"""Callback Dash per interattivita' — Black Point Roma."""

from __future__ import annotations

import logging
import traceback
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, html, dash_table
from dash.exceptions import PreventUpdate

try:
    from scipy import stats as sp_stats
except ImportError:
    sp_stats = None

from dashboard.layouts import COLORI_FASCE, ORDINE_FASCE

log = logging.getLogger("dashboard.callbacks")

_SFONDO = "#1e1e2e"
_TESTO = "#cdd6f4"
_GRIGLIA = "#313244"

_LAYOUT_BASE = dict(
    paper_bgcolor=_SFONDO,
    plot_bgcolor=_SFONDO,
    font_color=_TESTO,
    margin=dict(l=40, r=20, t=20, b=40),
)

_ScatterMap = getattr(go, "Scattermap", None) or getattr(go, "Scattermapbox", None)
_MAP_KEY = "map" if hasattr(go, "Scattermap") else "mapbox"

# Sequential YlOrRd 8-class for excess EPDO gradient (low → high).
_SCALA_EPDO = [
    "#ffffb2", "#fed976", "#feb24c", "#fd8d3c",
    "#fc4e2a", "#e31a1c", "#bd0026", "#800026",
]


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


def _msg_placeholder(testo: str) -> Any:
    return html.P(testo, style={"color": "#6c7086", "fontStyle": "italic",
                                "fontSize": "14px"})


def _icp_da_pesi(d: pd.DataFrame, pesi: dict) -> pd.Series:
    """Calcola la serie ICP da pesi (non normalizzati) e componenti A..D."""
    tot = sum(pesi.values()) or 1
    wA, wB, wC, wD = (pesi["A"] / tot, pesi["B"] / tot,
                      pesi["C"] / tot, pesi["D"] / tot)
    return (wA * d["A_norm"].fillna(0) + wB * d["B_norm"].fillna(0)
            + wC * d["C_norm"].fillna(0) + wD * d["D_norm"].fillna(0))


def _ricalcola_icp_fasce(df: pd.DataFrame, pesi: dict) -> pd.DataFrame:
    """Ricalcola ICP e fasce con pesi custom, restituendo una copia."""
    out = df.copy()
    out["ICP"] = _icp_da_pesi(df, pesi)
    soglie = [np.nanpercentile(out["ICP"], p) for p in [20, 40, 60, 80]]
    condizioni = [out["ICP"] <= soglie[0], out["ICP"] <= soglie[1],
                  out["ICP"] <= soglie[2], out["ICP"] <= soglie[3]]
    nomi = ["monitoraggio", "bassa", "media", "alta", "altissima"]
    out["fascia_priorita"] = np.select(condizioni, nomi[:4], default="altissima")
    return out


# Pesi di default: l'ICP coincide con la componente A (Eccesso EB-EPDO).
_PESI_DEFAULT = {"A": 1.0, "B": 0.0, "C": 0.0, "D": 0.0}


def _tabella_ranking(d: pd.DataFrame, icp: pd.Series, n: int = 25) -> Any:
    """Costruisce una DataTable col ranking top-N per ICP dato."""
    dd = d.copy()
    dd["ICP"] = icp.loc[dd.index].values
    dd = dd.nlargest(n, "ICP")
    dd.insert(0, "Pos.", range(1, len(dd) + 1))
    rinomina = {
        "Pos.": "Pos.",
        "toponimo": "Sito",
        "ICP": "ICP",
        "n_incidenti": "Inc.",
        "excess_EPDO_i": "Ecc. EPDO",
    }
    cols = [c for c in ["Pos.", "toponimo", "ICP", "n_incidenti",
                        "excess_EPDO_i"] if c in dd.columns]
    dd = dd[cols].round(2)
    if dd.empty:
        return _msg_placeholder("Nessun sito per i filtri selezionati.")
    return dash_table.DataTable(
        data=dd.to_dict("records"),
        columns=[{"name": rinomina.get(c, c), "id": c} for c in cols],
        page_size=15,
        sort_action="native",
        style_header={"backgroundColor": "#313244", "color": _TESTO,
                      "fontWeight": "600", "fontSize": "11px", "border": "none"},
        style_cell={"backgroundColor": _SFONDO, "color": _TESTO,
                    "fontSize": "11px", "border": f"1px solid {_GRIGLIA}",
                    "padding": "4px 8px", "maxWidth": "220px",
                    "overflow": "hidden", "textOverflow": "ellipsis"},
    )


def registra_callbacks(app: Any, df: pd.DataFrame) -> None:
    from dashboard.layouts import (tab_mappa, tab_spf, tab_eb,
                                   tab_sensitivita, tab_decisionale)

    # ==================================================================
    # Callback 1: switch tab
    # ==================================================================
    @app.callback(
        Output("contenuto-tab", "children"),
        Input("tabs-principale", "value"),
    )
    def cambia_tab(valore: str) -> Any:
        if valore == "mappa":
            return tab_mappa()
        if valore == "spf":
            return tab_spf()
        if valore == "eb":
            return tab_eb()
        if valore == "sensitivita":
            return tab_sensitivita()
        return tab_decisionale()

    # ==================================================================
    # Callback 1b: aggiorna store pesi dagli slider
    # ==================================================================
    @app.callback(
        Output("pesi-correnti", "data"),
        Input("peso-A", "value"),
        Input("peso-B", "value"),
        Input("peso-C", "value"),
        Input("peso-D", "value"),
    )
    def aggiorna_pesi(pA, pB, pC, pD):
        return {"A": pA or 0, "B": pB or 0, "C": pC or 0, "D": pD or 0}

    # ==================================================================
    # Callback 2: mappa principale
    # ==================================================================
    @app.callback(
        Output("mappa-principale", "figure"),
        Input("filtro-tipo", "value"),
        Input("filtro-fascia", "value"),
        Input("slider-top-n", "value"),
        Input("pesi-correnti", "data"),
        Input("filtro-intersezioni", "value"),
        Input("filtro-metrica", "value"),
    )
    def aggiorna_mappa(tipi, fasce, top_n, pesi, filtro_int, metrica):
        try:
            df_w = _ricalcola_icp_fasce(df, pesi) if pesi else df

            mask = df_w["tipo_sito"].isin(tipi or []) & df_w["fascia_priorita"].isin(fasce or [])

            if filtro_int and filtro_int != "tutte" and "intersezione" in (tipi or []):
                is_sem = filtro_int == "semaforizzata"
                mask = mask & (
                    (df_w["tipo_sito"] != "intersezione")
                    | (df_w["is_semaforizzata"].fillna(False) == is_sem)
                )

            metrica_col = metrica if metrica in df_w.columns else "ICP"
            sub = df_w.loc[mask].nlargest(top_n, metrica_col)

            fig = go.Figure()

            # --- Color binning by excess_EPDO_i ---
            epdo_col = "excess_EPDO_i"
            if epdo_col not in sub.columns or sub[epdo_col].isna().all():
                epdo_col = "ICP"
            epdo_vals = sub[epdo_col].fillna(0)

            n_palette = len(_SCALA_EPDO)
            if len(epdo_vals) < 2 or epdo_vals.nunique() < 2:
                sub = sub.copy()
                sub["_cbin"] = 0
                bin_edges = [epdo_vals.min(), epdo_vals.max()]
                n_bins_actual = 1
            else:
                sub = sub.copy()
                try:
                    sub["_cbin"], bin_edges = pd.qcut(
                        epdo_vals, q=n_palette, retbins=True,
                        labels=False, duplicates="drop")
                    sub["_cbin"] = sub["_cbin"].fillna(0).astype(int)
                    n_bins_actual = int(sub["_cbin"].max()) + 1
                except (ValueError, TypeError):
                    sub["_cbin"] = 0
                    bin_edges = [epdo_vals.min(), epdo_vals.max()]
                    n_bins_actual = 1

            # Map bin index → color (spread across palette evenly)
            if n_bins_actual >= n_palette:
                bin_colors = _SCALA_EPDO[:n_bins_actual]
            elif n_bins_actual == 1:
                bin_colors = [_SCALA_EPDO[n_palette // 2]]
            else:
                step = (n_palette - 1) / max(n_bins_actual - 1, 1)
                bin_colors = [_SCALA_EPDO[int(round(i * step))]
                              for i in range(n_bins_actual)]

            bin_labels = []
            for i in range(n_bins_actual):
                lo = bin_edges[i] if i < len(bin_edges) else bin_edges[-1]
                hi = (bin_edges[i + 1] if i + 1 < len(bin_edges)
                      else bin_edges[-1])
                bin_labels.append(f"{lo:.0f}–{hi:.0f}")

            bins_shown = set()

            # --- Segments as lines ---
            seg = (sub[sub["tipo_sito"] == "segmento"]
                   if "segmento" in (tipi or []) else sub.iloc[:0])
            has_coords = ("geom_coords" in seg.columns) if not seg.empty else False

            if not seg.empty and has_coords:
                for bi in range(n_bins_actual):
                    seg_b = seg[seg["_cbin"] == bi]
                    if seg_b.empty:
                        continue
                    lats, lons = [], []
                    for coords in seg_b["geom_coords"]:
                        if not isinstance(coords, list) or not coords:
                            continue
                        for c in coords:
                            lons.append(c[0])
                            lats.append(c[1])
                        lons.append(None)
                        lats.append(None)

                    if lats:
                        bins_shown.add(bi)
                        fig.add_trace(_ScatterMap(
                            lat=lats, lon=lons,
                            mode="lines",
                            line=dict(color=bin_colors[bi], width=3),
                            name=f"Ecc. EPDO {bin_labels[bi]}",
                            legendgroup=f"ebin_{bi}",
                            hoverinfo="skip",
                        ))

                hover_seg = [
                    f"<b>{t}</b><br>Ecc. EPDO: {epdo:.1f}"
                    f"<br>Inc: {int(n)} | ICP: {icp:.1f}"
                    for t, epdo, n, icp in zip(
                        seg["toponimo"],
                        seg[epdo_col],
                        seg.get("n_incidenti", pd.Series(0, index=seg.index)),
                        seg["ICP"])
                ]
                fig.add_trace(_ScatterMap(
                    lat=seg["lat"].values, lon=seg["lon"].values,
                    mode="markers",
                    marker=dict(size=3, opacity=0.01,
                                color=[bin_colors[int(b)]
                                       for b in seg["_cbin"]]),
                    text=hover_seg, hoverinfo="text",
                    showlegend=False,
                    customdata=seg.index.tolist(),
                    name="",
                ))
            elif not seg.empty:
                for bi in range(n_bins_actual):
                    seg_b = seg[seg["_cbin"] == bi]
                    if seg_b.empty:
                        continue
                    bins_shown.add(bi)
                    hover = [
                        f"<b>{t}</b><br>Ecc. EPDO: {epdo:.1f}"
                        f"<br>Inc: {int(n)}"
                        for t, epdo, n in zip(
                            seg_b["toponimo"], seg_b[epdo_col],
                            seg_b.get("n_incidenti",
                                      pd.Series(0, index=seg_b.index)))
                    ]
                    fig.add_trace(_ScatterMap(
                        lat=seg_b["lat"].values, lon=seg_b["lon"].values,
                        mode="markers",
                        marker=dict(size=7, opacity=0.85,
                                    color=bin_colors[bi]),
                        text=hover, hoverinfo="text",
                        name=f"Ecc. EPDO {bin_labels[bi]}",
                        legendgroup=f"ebin_{bi}",
                        customdata=seg_b.index.tolist(),
                    ))

            # --- Intersections as points ---
            inter = (sub[sub["tipo_sito"] == "intersezione"]
                     if "intersezione" in (tipi or []) else sub.iloc[:0])
            if not inter.empty:
                topo_int = inter["toponimo"].where(
                    inter["toponimo"].astype(str).str.strip() != "",
                    other=inter.get(
                        "id_nodo", pd.Series("", index=inter.index)
                    ).apply(lambda x: f"Int. #{int(x)}"
                            if pd.notna(x) else "Intersezione"))
                for bi in range(n_bins_actual):
                    int_b = inter[inter["_cbin"] == bi]
                    if int_b.empty:
                        continue
                    show_leg = bi not in bins_shown
                    bins_shown.add(bi)
                    hover = [
                        f"<b>{t}</b><br>Ecc. EPDO: {epdo:.1f}"
                        f"<br>Inc: {int(n)} | ICP: {icp:.1f}"
                        for t, epdo, n, icp in zip(
                            topo_int.loc[int_b.index],
                            int_b[epdo_col],
                            int_b.get("n_incidenti",
                                      pd.Series(0, index=int_b.index)),
                            int_b["ICP"])
                    ]
                    fig.add_trace(_ScatterMap(
                        lat=int_b["lat"].values, lon=int_b["lon"].values,
                        mode="markers",
                        marker=dict(size=9, opacity=0.9,
                                    color=bin_colors[bi]),
                        text=hover, hoverinfo="text",
                        name=f"Ecc. EPDO {bin_labels[bi]}",
                        legendgroup=f"ebin_{bi}",
                        showlegend=show_leg,
                        customdata=int_b.index.tolist(),
                    ))

            layout_map = {
                _MAP_KEY: dict(
                    style="open-street-map",
                    center=dict(lat=41.9028, lon=12.4964),
                    zoom=11,
                ),
            }
            map_layout = {**_LAYOUT_BASE, **layout_map,
                          "margin": dict(l=0, r=0, t=0, b=0)}
            fig.update_layout(
                **map_layout,
                legend=dict(bgcolor="#11111b", font=dict(color=_TESTO, size=10),
                            x=0.01, y=0.99, xanchor="left", yanchor="top"),
                showlegend=True, uirevision="mappa",
            )
            return fig
        except Exception:
            log.error("Errore in aggiorna_mappa:\n%s", traceback.format_exc())
            return _figura_vuota("Errore nel rendering della mappa")

    # ==================================================================
    # Callback 3: sito selezionato
    # ==================================================================
    @app.callback(
        Output("sito-selezionato", "data"),
        Input("mappa-principale", "clickData"),
    )
    def aggiorna_sito_sel(click_data):
        if not click_data:
            raise PreventUpdate
        pt = click_data["points"][0]
        idx = pt.get("customdata")
        if idx is None:
            idx = pt.get("pointIndex")
        if idx is None:
            raise PreventUpdate
        if isinstance(idx, list):
            idx = idx[0]
        try:
            return df.loc[idx].to_dict()
        except KeyError:
            raise PreventUpdate

    # ==================================================================
    # Callback 4: dettaglio sito
    # ==================================================================
    @app.callback(
        Output("dettaglio-header", "children"),
        Output("radar-componenti", "figure"),
        Output("bar-gravita", "figure"),
        Input("sito-selezionato", "data"),
    )
    def aggiorna_dettaglio(sito):
        if not sito:
            v = _figura_vuota("Nessun sito selezionato")
            return [_msg_placeholder("Seleziona un sito sulla mappa.")], v, v

        try:
            fascia = sito.get("fascia_priorita", "")
            colore = COLORI_FASCE.get(fascia, _TESTO)
            nome_raw = sito.get("toponimo", "")
            nome = nome_raw if isinstance(nome_raw, str) and nome_raw.strip() else (
                f"Intersezione #{sito.get('id_nodo', '')}" if sito.get("tipo_sito") == "intersezione"
                else str(sito.get("id_segmento", "Sito")))

            icp = sito.get("ICP", 0)
            tipo = sito.get("tipo_sito", "")

            header = [
                html.Div([
                    html.Span(fascia.upper(),
                              style={"backgroundColor": colore, "color": "#11111b",
                                     "borderRadius": "4px", "padding": "2px 8px",
                                     "fontSize": "11px", "fontWeight": "700"}),
                    html.Span(f"  ICP: {icp:.1f}",
                              style={"color": _TESTO, "fontSize": "13px",
                                     "marginLeft": "8px"}),
                ], style={"marginBottom": "8px"}),
                html.P(nome, style={"color": _TESTO, "fontWeight": "600",
                                    "fontSize": "14px", "margin": "0"}),
                html.P(f"{tipo.capitalize()} | Inc: {int(sito.get('n_incidenti',0))} | "
                       f"Costo: {sito.get('costo_sociale_eccesso_eur',0):,.0f} EUR",
                       style={"color": "#6c7086", "fontSize": "12px",
                              "margin": "4px 0 0 0"}),
            ]

            vals = [sito.get("A_norm", 0), sito.get("B_norm", 0),
                    sito.get("C_norm", 0), sito.get("D_norm", 0)]
            labs = ["Eccesso EB", "Severita'", "Vulnerabilita'", "Disp. vel."]
            fig_r = go.Figure()
            fig_r.add_trace(go.Scatterpolar(
                r=vals + [vals[0]], theta=labs + [labs[0]], fill="toself",
                fillcolor="rgba(231,76,60,0.25)",
                line=dict(color="#e74c3c", width=2), name="Sito"))
            fig_r.add_trace(go.Scatterpolar(
                r=[50]*5, theta=labs + [labs[0]],
                line=dict(color="#6c7086", width=1, dash="dot"), name="Media"))
            fig_r.update_layout(
                **{**_LAYOUT_BASE, "margin": dict(l=30, r=30, t=20, b=20)},
                polar=dict(bgcolor=_SFONDO,
                           radialaxis=dict(range=[0, 100], gridcolor=_GRIGLIA,
                                           tickfont=dict(size=9, color="#6c7086")),
                           angularaxis=dict(gridcolor=_GRIGLIA,
                                            tickfont=dict(size=10, color=_TESTO))),
                showlegend=True,
                legend=dict(font=dict(size=9, color=_TESTO), bgcolor=_SFONDO),
            )

            grav = {"Mortali": int(sito.get("n_mortali", 0)),
                    "Feriti": int(sito.get("n_feriti", 0)),
                    "Solo danni": int(sito.get("n_solo_danni", 0))}
            fig_b = go.Figure(go.Bar(
                x=list(grav.values()), y=list(grav.keys()), orientation="h",
                marker_color=["#8b0000", "#e67e22", "#f1c40f"]))
            fig_b.update_layout(**{**_LAYOUT_BASE, "margin": dict(l=80, r=20, t=10, b=30)},
                                xaxis=dict(gridcolor=_GRIGLIA, tickfont=dict(size=10)),
                                yaxis=dict(tickfont=dict(size=10)))
            return header, fig_r, fig_b
        except Exception:
            log.error("Errore in aggiorna_dettaglio:\n%s", traceback.format_exc())
            v = _figura_vuota("Errore")
            return [_msg_placeholder("Errore nel dettaglio.")], v, v

    # ==================================================================
    # Callback 5: Tab SPF — dropdown categorie
    # ==================================================================
    @app.callback(
        Output("spf-categoria", "options"),
        Input("spf-tipo-sito", "value"),
    )
    def aggiorna_categorie_spf(tipo):
        sub = df[df["tipo_sito"] == tipo]
        col = "spf_categoria" if "spf_categoria" in sub.columns else "categoria_spf"
        cats = sorted(sub[col].dropna().unique())
        return [{"label": c, "value": c} for c in cats]

    # ==================================================================
    # Callback 6: Tab SPF — grafici
    # ==================================================================
    @app.callback(
        Output("spf-scatter-oe", "figure"),
        Output("spf-residui", "figure"),
        Output("spf-hist-incidenti", "figure"),
        Output("spf-riepilogo-modelli", "children"),
        Input("spf-tipo-sito", "value"),
        Input("spf-categoria", "value"),
    )
    def aggiorna_spf(tipo, categorie):
        try:
            sub = df[df["tipo_sito"] == tipo].copy()
            col_cat = "spf_categoria" if "spf_categoria" in sub.columns else "categoria_spf"
            if categorie:
                sub = sub[sub[col_cat].isin(categorie)]
            sub = sub[sub["E_i"].notna() & (sub["E_i"] > 0)].copy()

            if sub.empty:
                v = _figura_vuota("Nessun dato")
                return v, v, v, _msg_placeholder("Nessun dato.")

            n_bins = min(20, max(5, len(sub) // 200))
            sub["E_bin"] = pd.qcut(sub["E_i"], q=n_bins, duplicates="drop")
            binned = sub.groupby("E_bin", observed=True).agg(
                E_media=("E_i", "mean"), O_media=("n_incidenti", "mean"),
                n_siti=("n_incidenti", "count")).reset_index()

            fig_oe = go.Figure()
            e_max = max(binned["E_media"].max(), binned["O_media"].max()) * 1.1
            fig_oe.add_trace(go.Scatter(
                x=[0, e_max], y=[0, e_max], mode="lines",
                line=dict(color="#6c7086", dash="dash", width=1), name="Bisettrice"))

            cats_uniche = sorted(sub[col_cat].unique())
            colori_cat = ["#89b4fa", "#f38ba8", "#a6e3a1", "#fab387",
                          "#cba6f7", "#94e2d5", "#f9e2af"]
            for i, cat in enumerate(cats_uniche):
                sc = sub[sub[col_cat] == cat]
                b = sc.groupby("E_bin", observed=True).agg(
                    E_media=("E_i", "mean"), O_media=("n_incidenti", "mean"),
                    n=("n_incidenti", "count")).reset_index()
                sz = (b["n"] / b["n"].max() * 14 + 4).clip(upper=20)
                fig_oe.add_trace(go.Scatter(
                    x=b["E_media"], y=b["O_media"], mode="markers+lines",
                    marker=dict(size=sz, color=colori_cat[i % len(colori_cat)],
                                opacity=0.8),
                    line=dict(color=colori_cat[i % len(colori_cat)], width=1),
                    name=cat, text=[f"n={v}" for v in b["n"]],
                    hoverinfo="text+x+y"))

            fig_oe.update_layout(**_LAYOUT_BASE,
                                 xaxis=dict(title="E (predetto SPF)", gridcolor=_GRIGLIA),
                                 yaxis=dict(title="O (osservato medio)", gridcolor=_GRIGLIA))

            # Residui di Pearson
            k = sub["k_spf"].clip(lower=1e-9)
            var_nb = sub["E_i"] + sub["E_i"] ** 2 * k
            residui = (sub["n_incidenti"] - sub["E_i"]) / np.sqrt(var_nb.clip(lower=1e-9))
            residui = residui.replace([np.inf, -np.inf], np.nan).dropna().clip(-5, 5)

            fig_res = go.Figure()
            fig_res.add_trace(go.Histogram(x=residui, nbinsx=60,
                                           marker_color="#89b4fa", opacity=0.7))
            fig_res.add_vline(x=0, line_dash="dash", line_color="#6c7086")
            fig_res.update_layout(**_LAYOUT_BASE,
                                  xaxis=dict(title="Residuo di Pearson", gridcolor=_GRIGLIA),
                                  yaxis=dict(title="Frequenza", gridcolor=_GRIGLIA))

            # Istogramma incidenti
            fig_hist = go.Figure()
            inc_clip = sub["n_incidenti"].clip(
                upper=sub["n_incidenti"].quantile(0.99))
            fig_hist.add_trace(go.Histogram(x=inc_clip, nbinsx=50,
                                            marker_color="#a6e3a1", opacity=0.7))
            fig_hist.update_layout(
                **_LAYOUT_BASE,
                xaxis=dict(title="N. incidenti per sito", gridcolor=_GRIGLIA),
                yaxis=dict(title="Frequenza", gridcolor=_GRIGLIA, type="log"))

            # Riepilogo modelli
            righe_mod = []
            for cat in cats_uniche:
                sc = sub[sub[col_cat] == cat]
                righe_mod.append({
                    "Categoria": cat,
                    "N siti": len(sc),
                    "Inc. totali": int(sc["n_incidenti"].sum()),
                    "k": f"{sc['k_spf'].iloc[0]:.4f}" if len(sc) > 0 else "-",
                    "E medio": f"{sc['E_i'].mean():.2f}",
                    "O medio": f"{sc['n_incidenti'].mean():.2f}",
                })
            tab_mod = dash_table.DataTable(
                data=righe_mod,
                columns=[{"name": k, "id": k}
                         for k in righe_mod[0]] if righe_mod else [],
                style_header={"backgroundColor": "#313244", "color": _TESTO,
                              "fontWeight": "600", "fontSize": "11px",
                              "border": "none"},
                style_cell={"backgroundColor": _SFONDO, "color": _TESTO,
                            "fontSize": "11px",
                            "border": f"1px solid {_GRIGLIA}",
                            "padding": "4px 8px"},
            )
            return fig_oe, fig_res, fig_hist, tab_mod
        except Exception:
            log.error("Errore in aggiorna_spf:\n%s", traceback.format_exc())
            v = _figura_vuota("Errore nel calcolo")
            return v, v, v, _msg_placeholder("Errore.")

    # ==================================================================
    # Callback 7: Tab EB
    # ==================================================================
    @app.callback(
        Output("eb-hist-excess", "figure"),
        Output("eb-hist-epdo", "figure"),
        Output("eb-scatter-peso", "figure"),
        Output("eb-tabella-top", "data"),
        Output("eb-tabella-top", "columns"),
        Input("eb-tipo-sito", "value"),
    )
    def aggiorna_eb(tipo):
        try:
            sub = df[df["tipo_sito"] == tipo].copy()
            sub = sub[sub["excess_i"].notna()]
            if sub.empty:
                v = _figura_vuota("Nessun dato")
                return v, v, v, [], []

            ex_clip = sub["excess_i"].clip(
                lower=sub["excess_i"].quantile(0.01),
                upper=sub["excess_i"].quantile(0.99))
            fig_ex = go.Figure()
            fig_ex.add_trace(go.Histogram(x=ex_clip, nbinsx=80,
                                          marker_color="#89b4fa", opacity=0.7))
            fig_ex.add_vline(x=0, line_dash="dash", line_color="#f38ba8")
            fig_ex.update_layout(
                **_LAYOUT_BASE,
                xaxis=dict(title="excess_i (EB - E)", gridcolor=_GRIGLIA),
                yaxis=dict(title="Frequenza", gridcolor=_GRIGLIA))

            epdo_clip = sub["excess_EPDO_i"].clip(
                lower=sub["excess_EPDO_i"].quantile(0.01),
                upper=sub["excess_EPDO_i"].quantile(0.99))
            fig_epdo = go.Figure()
            fig_epdo.add_trace(go.Histogram(x=epdo_clip, nbinsx=80,
                                            marker_color="#f38ba8", opacity=0.7))
            fig_epdo.add_vline(x=0, line_dash="dash", line_color="#89b4fa")
            fig_epdo.update_layout(
                **_LAYOUT_BASE,
                xaxis=dict(title="excess EPDO", gridcolor=_GRIGLIA),
                yaxis=dict(title="Frequenza", gridcolor=_GRIGLIA))

            fig_w = go.Figure()
            samp = sub.sample(min(5000, len(sub)), random_state=42)
            fig_w.add_trace(go.Scatter(
                x=samp["n_incidenti"], y=samp["w_i"], mode="markers",
                marker=dict(size=3, color="#a6e3a1", opacity=0.4),
                hoverinfo="x+y"))
            fig_w.update_layout(
                **_LAYOUT_BASE,
                xaxis=dict(title="N. incidenti osservati",
                           gridcolor=_GRIGLIA, type="log"),
                yaxis=dict(title="Peso EB (w_i)", gridcolor=_GRIGLIA,
                           range=[0, 1.05]))

            col_nome = "toponimo"
            cols_show = [col_nome, "n_incidenti", "E_i", "EB_i", "excess_i",
                         "excess_EPDO_i", "costo_sociale_eccesso_eur"]
            cols_show = [c for c in cols_show if c in sub.columns]
            top = sub.nlargest(30, "excess_EPDO_i")[cols_show].round(2)
            return (fig_ex, fig_epdo, fig_w,
                    top.to_dict("records"),
                    [{"name": c, "id": c} for c in cols_show])
        except Exception:
            log.error("Errore in aggiorna_eb:\n%s", traceback.format_exc())
            v = _figura_vuota("Errore")
            return v, v, v, [], []

    # ==================================================================
    # Callback 8a: Tab Sensitivita' — opzioni dropdown categoria segmenti
    # ==================================================================
    @app.callback(
        Output("sens-filtro-categoria", "options"),
        Input("tabs-principale", "value"),
    )
    def aggiorna_cat_sens(tab):
        col = "spf_categoria" if "spf_categoria" in df.columns else "categoria_spf"
        seg = df[df["tipo_sito"] == "segmento"]
        cats = sorted(seg[col].dropna().unique())
        return [{"label": c, "value": c} for c in cats]

    # ==================================================================
    # Callback 8b: Tab Sensitivita' — ranking default vs pesi custom
    # ==================================================================
    @app.callback(
        Output("pesi-normalizzati", "children"),
        Output("sens-rho-seg", "children"),
        Output("sens-rho-int", "children"),
        Output("sens-rank-seg-default", "children"),
        Output("sens-rank-int-default", "children"),
        Output("sens-rank-seg-nuovo", "children"),
        Output("sens-rank-int-nuovo", "children"),
        Input("peso-A", "value"),
        Input("peso-B", "value"),
        Input("peso-C", "value"),
        Input("peso-D", "value"),
        Input("sens-filtro-categoria", "value"),
        Input("sens-filtro-int", "value"),
    )
    def aggiorna_sensitivita(pA, pB, pC, pD, categorie, tipo_int):
        try:
            pesi = {"A": pA or 0, "B": pB or 0, "C": pC or 0, "D": pD or 0}
            tot = sum(pesi.values()) or 1
            wA, wB, wC, wD = (pesi["A"] / tot, pesi["B"] / tot,
                              pesi["C"] / tot, pesi["D"] / tot)
            pesi_txt = (f"Normalizzati: A={wA:.2f}  B={wB:.2f}  "
                        f"C={wC:.2f}  D={wD:.2f}")

            col_cat = ("spf_categoria" if "spf_categoria" in df.columns
                       else "categoria_spf")

            # Sottoinsiemi filtrati.
            seg = df[df["tipo_sito"] == "segmento"].copy()
            if categorie:
                seg = seg[seg[col_cat].isin(categorie)]

            inter = df[df["tipo_sito"] == "intersezione"].copy()
            if tipo_int and tipo_int != "tutte" and "is_semaforizzata" in inter.columns:
                vuoi_sem = tipo_int == "semaforizzata"
                inter = inter[inter["is_semaforizzata"].fillna(False) == vuoi_sem]

            # ICP default (solo Eccesso EPDO) e personalizzato.
            icp_seg_def = _icp_da_pesi(seg, _PESI_DEFAULT)
            icp_int_def = _icp_da_pesi(inter, _PESI_DEFAULT)
            icp_seg_new = _icp_da_pesi(seg, pesi)
            icp_int_new = _icp_da_pesi(inter, pesi)

            # Spearman rho fra ranking default e personalizzato (per tipo).
            def _rho(icp_def: pd.Series, icp_new: pd.Series) -> float:
                if sp_stats is None or len(icp_def) < 11:
                    return float("nan")
                r_def = icp_def.rank(ascending=False, method="min")
                r_new = icp_new.rank(ascending=False, method="min")
                ok = r_def.notna() & r_new.notna()
                if ok.sum() < 11:
                    return float("nan")
                rho, _ = sp_stats.spearmanr(r_def[ok], r_new[ok])
                return rho

            def _rho_span(label: str, rho: float) -> Any:
                if not np.isfinite(rho):
                    return html.Span(f"{label}: N/D",
                                     style={"color": "#6c7086"})
                colore = ("#a6e3a1" if rho > 0.95
                          else "#f9e2af" if rho > 0.85 else "#f38ba8")
                return html.Span(f"{label}: {rho:.3f}",
                                 style={"color": colore})

            rho_seg = _rho(icp_seg_def, icp_seg_new)
            rho_int = _rho(icp_int_def, icp_int_new)

            return (
                pesi_txt,
                _rho_span("Segmenti", rho_seg),
                _rho_span("Intersezioni", rho_int),
                _tabella_ranking(seg, icp_seg_def),
                _tabella_ranking(inter, icp_int_def),
                _tabella_ranking(seg, icp_seg_new),
                _tabella_ranking(inter, icp_int_new),
            )
        except Exception:
            log.error("Errore in aggiorna_sensitivita:\n%s",
                      traceback.format_exc())
            err = _msg_placeholder("Errore")
            return ("Errore", "", "", err, err, err, err)

    # ==================================================================
    # Callback 9: Tab Decisionale — dropdown categorie
    # ==================================================================
    @app.callback(
        Output("dec-filtro-categoria", "options"),
        Input("tabs-principale", "value"),
    )
    def aggiorna_cat_dec(tab):
        col = "spf_categoria" if "spf_categoria" in df.columns else "categoria_spf"
        cats = sorted(df[col].dropna().unique())
        return [{"label": c, "value": c} for c in cats]

    # ==================================================================
    # Callback 10: Tab Decisionale — grafici e tabella
    # ==================================================================
    @app.callback(
        Output("scatter-matrice", "figure"),
        Output("bar-fasce", "figure"),
        Output("tabella-top", "data"),
        Output("tabella-top", "columns"),
        Input("tabs-principale", "value"),
        Input("dec-filtro-categoria", "value"),
        Input("pesi-correnti", "data"),
    )
    def aggiorna_decisionale(tab, categorie, pesi):
        if tab != "decisionale":
            raise PreventUpdate

        try:
            df_w = _ricalcola_icp_fasce(df, pesi) if pesi else df
            col_cat = ("spf_categoria" if "spf_categoria" in df_w.columns
                       else "categoria_spf")
            sub = df_w.copy()
            if categorie:
                sub = sub[sub[col_cat].isin(categorie)]

            fig_sc = go.Figure()
            for fascia in ORDINE_FASCE:
                pf = sub[sub["fascia_priorita"] == fascia]
                if pf.empty:
                    continue
                samp = pf.sample(min(2000, len(pf)), random_state=42)
                fig_sc.add_trace(go.Scatter(
                    x=samp["excess_EPDO_i"].clip(lower=-50),
                    y=samp["B_norm"], mode="markers",
                    marker=dict(size=4, color=COLORI_FASCE[fascia], opacity=0.6),
                    name=fascia.capitalize(),
                    text=[f"ICP: {v:.1f}" for v in samp["ICP"]],
                    hoverinfo="text"))
            fig_sc.update_layout(
                **_LAYOUT_BASE,
                xaxis=dict(title="Eccesso EPDO", gridcolor=_GRIGLIA,
                           zeroline=True, zerolinecolor="#6c7086"),
                yaxis=dict(title="Severita' (norm.)", gridcolor=_GRIGLIA,
                           zeroline=True, zerolinecolor="#6c7086"),
                legend=dict(bgcolor=_SFONDO,
                            font=dict(size=10, color=_TESTO)))

            cs = (sub[sub["tipo_sito"] == "segmento"]["fascia_priorita"]
                  .value_counts().reindex(ORDINE_FASCE, fill_value=0))
            ci = (sub[sub["tipo_sito"] == "intersezione"]["fascia_priorita"]
                  .value_counts().reindex(ORDINE_FASCE, fill_value=0))
            fig_bar = go.Figure([
                go.Bar(name="Segmenti", x=ORDINE_FASCE, y=cs.values,
                       marker_color=[COLORI_FASCE[f] for f in ORDINE_FASCE],
                       opacity=0.85),
                go.Bar(name="Intersezioni", x=ORDINE_FASCE, y=ci.values,
                       marker_color=[COLORI_FASCE[f] for f in ORDINE_FASCE],
                       opacity=0.5),
            ])
            fig_bar.update_layout(
                **_LAYOUT_BASE, barmode="group",
                xaxis=dict(tickfont=dict(size=10)),
                yaxis=dict(gridcolor=_GRIGLIA, tickfont=dict(size=10)),
                legend=dict(bgcolor=_SFONDO,
                            font=dict(size=10, color=_TESTO)))

            cols_tab = ["rank", "tipo_sito", "toponimo", "fascia_priorita",
                        "ICP", "A_norm", "B_norm",
                        "C_norm", "D_norm", "n_incidenti", "excess_EPDO_i",
                        "costo_sociale_eccesso_eur"]
            top_combined = sub.nlargest(50, "ICP").copy()
            top_combined.insert(0, "rank", range(1, len(top_combined) + 1))
            cols_tab = [c for c in cols_tab if c in top_combined.columns]
            top_combined = top_combined[cols_tab].round(2)
            return (fig_sc, fig_bar,
                    top_combined.to_dict("records"),
                    [{"name": c, "id": c} for c in cols_tab])
        except Exception:
            log.error("Errore in aggiorna_decisionale:\n%s",
                      traceback.format_exc())
            v = _figura_vuota("Errore")
            return v, v, [], []
