// Title: sfCp.js — Stockfish centipawn bar chart
// Description:
//   Renders a Plotly bar chart of Stockfish cp_eval per ply, capped at ±12 pawns,
//   with perspective-flipping (white/black), background shading to indicate which
//   side is ahead, per-move colour from move-quality classes, click-to-set-ply,
//   and ply-marker synchronisation via WoodLeagueAnalysis shared state.
//   Data is read from the `sf-cp-data` JSON-script element emitted by the partial.
//
// Changelog:
//   2026-05-21 (#186): Lifted from analysis.html inline script; wired to sf-cp-data.

(function () {
  var rawPayload = JSON.parse(document.getElementById("sf-cp-data").textContent || "null");
  var div = document.getElementById("sf-cp-chart");
  if (!div || !rawPayload || typeof Plotly === "undefined") return;

  var theme = window.WoodLeagueChartTheme;

  /** Maximum absolute centipawn value treated as a forced-mate signal. */
  var MATE_THRESHOLD = 9000;

  /** Display cap in centipawns (= 12 pawns). */
  var DISPLAY_CAP = 1200;

  /**
   * Pre-process the raw payload into normalised point objects.
   *
   * Params:
   *   payload (Array): Array of {ply, cp_eval, mate_in, classification, san} from server.
   *
   * Returns:
   *   Array of {ply, cp, display, san, cls} where display is capped and mate scores
   *   are pinned to ±DISPLAY_CAP.
   */
  var rawPoints = rawPayload.map(function (d) {
    var cp = Number(d.cp_eval || 0);
    var isMate = Math.abs(cp) >= MATE_THRESHOLD;
    var display = isMate
      ? cp >= 0 ? DISPLAY_CAP : -DISPLAY_CAP
      : Math.max(-DISPLAY_CAP, Math.min(DISPLAY_CAP, cp));
    return {
      ply: Number(d.ply),
      cp: cp,
      display: display,
      san: d.san || "",
      cls: (d.classification || "").toLowerCase(),
    };
  });

  // Fixed in-card height (#216): chart lives inside the SF stat card, so
  // it must not grow with ply count or it overflows the card.
  var chartHeight = 282;

  /**
   * Resolve a move-quality classification to its actual CSS background colour
   * by mounting a hidden swatch with the .move-annotation-<cls> class and
   * reading getComputedStyle. Cached after first lookup. (#216 fix — previously
   * the chart passed raw CSS class names to Plotly's marker.color, which
   * silently fell back to a default.)
   *
   * Params:
   *   cls (string): Lowercase classification, e.g. "best", "blunder", or "".
   *
   * Returns:
   *   CSS colour string (rgb/rgba) usable as Plotly marker.color.
   */
  var colorCache = {};
  function resolveAnnotationColor(cls) {
    if (!cls) return theme.colors.barDefault;
    if (colorCache[cls]) return colorCache[cls];
    var swatch = document.createElement("div");
    swatch.className = "move-annotation-" + cls;
    swatch.style.position = "absolute";
    swatch.style.visibility = "hidden";
    swatch.style.pointerEvents = "none";
    document.body.appendChild(swatch);
    var bg = window.getComputedStyle(swatch).backgroundColor;
    document.body.removeChild(swatch);
    // getComputedStyle returns "rgba(0, 0, 0, 0)" for unmatched/transparent;
    // fall back to the chart's default in that case.
    var resolved = (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent")
      ? bg
      : theme.colors.barDefault;
    colorCache[cls] = resolved;
    return resolved;
  }

  /**
   * Return points adjusted for the given perspective.
   *
   * When perspective is "black" the cp sign is negated (so Black advantage
   * shows as positive) and the display value is also negated.  In both cases
   * the display value is further negated so that positive advantage points
   * downward (toward the favoured side's pieces at the bottom of the board).
   *
   * Params:
   *   perspective (string): "white" or "black".
   *
   * Returns:
   *   Array of point objects with adjusted cp/display fields.
   */
  function getPointsForPerspective(perspective) {
    var points = rawPoints;
    if (perspective === "black") {
      points = rawPoints.map(function (p) {
        return { ply: p.ply, cp: -p.cp, display: -p.display, san: p.san, cls: p.cls };
      });
    }
    // Invert display so advantage bars point downward.
    return points.map(function (p) {
      return { ply: p.ply, cp: p.cp, display: -p.display, san: p.san, cls: p.cls };
    });
  }

  /**
   * Build the background shading rectangles for the chart.
   *
   * White background fills the region that represents White advantage;
   * dark background fills the region representing Black advantage.
   * The regions swap when perspective is "black".
   *
   * Params:
   *   perspective (string): "white" or "black".
   *
   * Returns:
   *   Array of Plotly shape objects.
   */
  /**
   * Build solid "endcap" rectangles at the tip of each classified bar —
   * same visual treatment as the chips' top-border. Each cap spans the
   * bar's full x width and extends from the bar tip inward toward zero
   * by roughly 5px (converted to y-units via the chart's height-to-range
   * ratio), so the cap sits ON TOP of the bar rather than straddling it.
   */
  function buildShapes(perspective) {
    var pts = getPointsForPerspective(perspective);
    // Approximate 5px in y-units. Plot area ≈ chartHeight - top/bottom
    // margins; y range is 2 * DISPLAY_CAP.
    var plotAreaPx = chartHeight - 26 - 40;
    var capPx = 5;
    var capY = (capPx / plotAreaPx) * (2 * DISPLAY_CAP);
    var shapes = [];
    for (var i = 0; i < pts.length; i++) {
      var p = pts[i];
      if (!p.cls) continue;
      // For positive display the bar grows upward; cap extends downward
      // from the tip. For negative display the bar grows downward; cap
      // extends upward. sign(0) → +1 (cosmetic; zero-bars have no tip).
      var sign = p.display >= 0 ? 1 : -1;
      shapes.push({
        type: "rect", xref: "x", yref: "y",
        x0: p.ply - 0.5, x1: p.ply + 0.5,
        y0: p.display,
        y1: p.display - capY * sign,
        fillcolor: resolveAnnotationColor(p.cls),
        line: { width: 0 },
        layer: "above",
      });
    }
    return shapes;
  }

  /**
   * Build the Plotly bar trace for the given perspective.
   *
   * Params:
   *   perspective (string): "white" or "black".
   *
   * Returns:
   *   Plotly trace object (type "bar").
   */
  /**
   * Build two stacked bar traces for the given perspective:
   *   - base: the previous ply's display value (neutral colour)
   *   - delta: the change introduced by this ply (classification colour,
   *     perspective-aware via buildColors)
   * Sum (base + delta) = current ply's display value, so the total bar
   * height still reads as the absolute evaluation. The eye picks out the
   * "this move's contribution" segment from the rest of the history.
   *
   * Params:
   *   perspective (string): "white" or "black".
   *
   * Returns:
   *   Array of two Plotly bar traces (base first, delta on top).
   */
  /**
   * Build the cumulative-cp bar trace. Classification is rendered via the
   * line "endcap" shapes (see buildShapes), not as a separate scatter.
   */
  function buildTraces(perspective) {
    var pts = getPointsForPerspective(perspective);
    var plies = pts.map(function (p) { return p.ply; });
    var BAR_GREEN = "#1A3A2A";

    var customdata = pts.map(function (p) {
      var isWhiteMove = (p.ply % 2) === 1;
      var player = isWhiteMove
        ? (window.ANALYSIS_DATA && window.ANALYSIS_DATA.white) || "White"
        : (window.ANALYSIS_DATA && window.ANALYSIS_DATA.black) || "Black";
      var cp = p.cp / 100;
      var sign = cp >= 0 ? "+" : "-";
      return [player, p.san, sign, Math.abs(cp).toFixed(2)];
    });

    var colors = pts.map(function (p) {
      return p.cls ? resolveAnnotationColor(p.cls) : BAR_GREEN;
    });

    return [
      {
        x: plies,
        y: pts.map(function (p) { return p.display; }),
        type: "bar",
        marker: { color: colors },
        customdata: customdata,
        hovertemplate:
          "%{customdata[0]} played %{customdata[1]} " +
          "(%{customdata[2]}%{customdata[3]} pawns)<extra></extra>",
        showlegend: false,
        name: "Eval",
      },
    ];
  }

  /**
   * Build the Plotly layout object for the given perspective.
   *
   * Params:
   *   perspective (string): "white" or "black".
   *
   * Returns:
   *   Plotly layout object.
   */
  function buildLayout(perspective) {
    var monoFont = { size: 11, color: theme.colors.text, family: theme.fonts.mono };
    // Pawn-unit tick labels (e.g. "+5", "-5") instead of raw centipawns, so
    // the y-axis stays narrow enough to match the LC0 chart's left margin (#216).
    // Butterfly axis: magnitudes are positive in both directions; the
    // top-of-chart annotation names which side the upper half belongs to.
    var tickvals = [-1200, -600, 0, 600, 1200];
    var ticktext = tickvals.map(function (v) {
      if (v === 0) return "0";
      return "+" + (Math.abs(v) / 100);
    });
    // In white perspective the top half is Black-advantage (positive
    // display) and the bottom is White-advantage; black perspective swaps.
    var topLabel = perspective === "white" ? "Black Advantage" : "White Advantage";
    var bottomLabel = perspective === "white" ? "White Advantage" : "Black Advantage";
    return {
      xaxis: { zeroline: false, showgrid: false, showticklabels: false },
      yaxis: {
        zeroline: true, zerolinecolor: theme.colors.textBold,
        showgrid: false,
        tickfont: monoFont,
        tickvals: tickvals,
        ticktext: ticktext,
      },
      margin: { l: 36, r: 8, t: 26, b: 40 },
      height: chartHeight,
      paper_bgcolor: "rgba(0,0,0,0)",
      // Dark-cream plot background matching the move-chip parchment tone
      // (--color-parchment, #F5F0E8) so the chart sits in the same warm
      // palette family as the chips and card surfaces (#216).
      plot_bgcolor: "#FBF7EE",
      font: { color: theme.colors.text, family: theme.fonts.serif },
      // "closest" instead of "x unified" so each bar's tooltip is owned
      // by its hovertemplate — no separate "ply N" header on top.
      hovermode: "closest",
      bargap: 0,
      // Hover label styled to match the site's .card-pop tooltips:
      // cream background, ebony border + text, EB Garamond serif body.
      hoverlabel: {
        bgcolor: "#FAF7F0",
        bordercolor: theme.colors.textBold,
        font: { color: theme.colors.textBold, family: theme.fonts.serif, size: 13 },
        align: "left",
      },
      annotations: [
        {
          text: topLabel,
          xref: "paper", yref: "paper",
          x: 0.5, y: 1.0, xanchor: "center", yanchor: "bottom",
          showarrow: false,
          font: { size: 12, color: theme.colors.textBold, family: theme.fonts.display },
        },
        {
          text: bottomLabel,
          xref: "paper", yref: "paper",
          x: 0.5, y: 0, xanchor: "center", yanchor: "top",
          yshift: -22,
          showarrow: false,
          font: { size: 12, color: theme.colors.textBold, family: theme.fonts.display },
        },
      ],
    };
  }

  /** Vertical dotted line marking the currently selected ply. */
  var highlight = {
    x: [null, null],
    y: [-DISPLAY_CAP, DISPLAY_CAP],
    mode: "lines",
    showlegend: false,
    hoverinfo: "skip",
    line: { color: theme.colors.highlight, width: 2, dash: "dot" },
  };

  var currentPerspective = WoodLeagueAnalysis.getState().perspective;

  // Force-load Playfair Display SC before Plotly renders so the SVG
  // annotation text (top/bottom "Advantage" labels) doesn't paint with the
  // serif fallback and stick.
  var fontReady = (document.fonts && document.fonts.load)
    ? document.fonts.load('12px "Playfair Display"')
    : Promise.resolve();

  // Trace order: 0 = base (previous score), 1 = delta (this move's change),
  // 2 = ply highlight marker.
  fontReady.then(function () { return Plotly.newPlot(
    div,
    buildTraces(currentPerspective).concat([highlight]),
    buildLayout(currentPerspective),
    { displaylogo: false, responsive: true }
  ); }).then(function () {
    /**
     * Click on any bar (base or delta) to jump shared ply state to that ply.
     */
    div.on("plotly_click", function (ev) {
      if (ev.points && ev.points.length) {
        WoodLeagueAnalysis.setPly(ev.points[0].x);
      }
    });

    /**
     * Subscribe to shared WoodLeagueAnalysis state changes.
     * Updates the ply marker and re-renders the chart when perspective flips.
     */
    WoodLeagueAnalysis.subscribe(function (state) {
      // Move the ply marker (trace index 1 — after the single bar trace).
      Plotly.restyle(div, { x: [[state.ply, state.ply]], y: [[-DISPLAY_CAP, DISPLAY_CAP]] }, [1]);

      if (state.perspective !== currentPerspective) {
        currentPerspective = state.perspective;
        var traces = buildTraces(currentPerspective);
        // Bar trace y flips with perspective; the colored endcap shapes
        // are rebuilt via the relayout below.
        Plotly.restyle(div, {
          y: [traces[0].y],
          customdata: [traces[0].customdata],
        }, [0]);
        Plotly.relayout(div, buildLayout(currentPerspective));
      }
    });
  });
})();
