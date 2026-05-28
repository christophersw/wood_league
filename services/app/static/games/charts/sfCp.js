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
  var chartHeight = 240;

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
   * Build the bar colour array from move-quality class colours.
   *
   * Only bars representing moves made by the perspective player are coloured;
   * the opposing side's bars use the chart's neutral default so the eye
   * focuses on the player's own move quality (#216).
   * Ply parity: odd = White's move, even = Black's.
   *
   * Params:
   *   perspective (string): "white" or "black".
   *
   * Returns:
   *   Array of CSS colour strings, one per point.
   */
  /**
   * Per-segment colour arrays for the stacked bar chart (#216).
   *
   * Each segment is coloured by which side it represents in WHITE-frame cp,
   * invariant of the current display perspective:
   *   - positive cp (white advantage) → white
   *   - negative cp (black advantage) → black
   * Ply 1's base segment defaults to white (starting position is even; the
   * "previous" position is no-one's advantage, but we need to pick a value).
   *
   * Returns:
   *   { base: string[], delta: string[] }
   */
  function buildSegmentColors() {
    // Base (previous score, historical) is solid dark green; side info now
    // reads from the zone-tinted background, not the bar colour. Delta
    // carries the move-quality classification colour when classified, so
    // the "this move's contribution" segment pops out.
    var BAR_GREEN = "#1A3A2A";  // --color-forest
    var base = [];
    var delta = [];
    for (var i = 0; i < rawPoints.length; i++) {
      var p = rawPoints[i];
      base.push(BAR_GREEN);
      delta.push(p.cls ? resolveAnnotationColor(p.cls) : BAR_GREEN);
    }
    return { base: base, delta: delta };
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
  function buildShapes(perspective) {
    // Zone tints: white-advantage zone gets a very light cream, almost
    // white; black-advantage zone gets a dark gray. The zones swap with
    // perspective (white-adv zone is at the bottom in white perspective,
    // top in black perspective).
    var WHITE_ZONE = "#FBF7EE";
    var BLACK_ZONE = "#6B6B6B";
    var bottomFill = perspective === "white" ? WHITE_ZONE : BLACK_ZONE;
    var topFill = perspective === "white" ? BLACK_ZONE : WHITE_ZONE;
    return [
      {
        type: "rect", xref: "paper", yref: "y",
        x0: 0, x1: 1, y0: -DISPLAY_CAP, y1: 0,
        fillcolor: bottomFill, line: { width: 0 }, layer: "below",
      },
      {
        type: "rect", xref: "paper", yref: "y",
        x0: 0, x1: 1, y0: 0, y1: DISPLAY_CAP,
        fillcolor: topFill, line: { width: 0 }, layer: "below",
      },
    ];
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
  function buildTraces(perspective) {
    var pts = getPointsForPerspective(perspective);
    var plies = pts.map(function (p) { return p.ply; });
    var baseY = [];
    var deltaY = [];
    var prev = 0;
    for (var i = 0; i < pts.length; i++) {
      baseY.push(prev);
      deltaY.push(pts[i].display - prev);
      prev = pts[i].display;
    }
    var colors = buildSegmentColors();
    return [
      {
        x: plies,
        y: baseY,
        type: "bar",
        marker: { color: colors.base },
        hoverinfo: "skip",
        showlegend: false,
        name: "Previous",
      },
      {
        x: plies,
        y: deltaY,
        type: "bar",
        marker: { color: colors.delta },
        customdata: pts.map(function (p, idx) {
          var delta = deltaY[idx] / 100;
          var cpDelta = -delta;
          var dsign = cpDelta >= 0 ? "+" : "-";
          var isWhiteMove = (p.ply % 2) === 1;
          var player = isWhiteMove
            ? (window.ANALYSIS_DATA && window.ANALYSIS_DATA.white) || "White"
            : (window.ANALYSIS_DATA && window.ANALYSIS_DATA.black) || "Black";
          return [
            p.san,
            dsign,
            Math.abs(cpDelta).toFixed(2),
            player,
          ];
        }),
        hovertemplate:
          "%{customdata[3]} played %{customdata[0]} " +
          "(Δ %{customdata[1]}%{customdata[2]})<extra></extra>",
        name: "Δ",
        showlegend: false,
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
      hovermode: "x unified",
      barmode: "relative",
      bargap: 0,
      hoverlabel: {
        bgcolor: "white", bordercolor: theme.colors.textBold,
        font: { color: theme.colors.textBold, family: theme.fonts.mono, size: 12 },
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
      // Move the ply marker (trace index 2 after the two bar traces).
      Plotly.restyle(div, { x: [[state.ply, state.ply]], y: [[-DISPLAY_CAP, DISPLAY_CAP]] }, [2]);

      if (state.perspective !== currentPerspective) {
        currentPerspective = state.perspective;
        var traces = buildTraces(currentPerspective);
        // Restyle base (0) and delta (1) bar traces. Only y values flip
        // with perspective — colours are side-bound and invariant.
        Plotly.restyle(div, {
          x: [traces[0].x, traces[1].x],
          y: [traces[0].y, traces[1].y],
        }, [0, 1]);
        Plotly.restyle(div, {
          customdata: [traces[1].customdata],
        }, [1]);
        Plotly.relayout(div, buildLayout(currentPerspective));
      }
    });
  });
})();
