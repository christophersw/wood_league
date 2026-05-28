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
  function buildSegmentColors(perspective) {
    // Colour by display zone so the perspective player's advantage (always
    // at the bottom of the chart) reads as the light "whiteAdvantage" tint
    // and the opponent's advantage (top) reads as the dark "blackAdvantage"
    // tint — regardless of perspective. Flipping perspective re-paints the
    // segments so the light/dark assignment tracks the perspective player.
    var pts = getPointsForPerspective(perspective);
    var base = [];
    var delta = [];
    var prevDisplay = 0;
    for (var i = 0; i < pts.length; i++) {
      var p = pts[i];
      base.push(prevDisplay <= 0
        ? theme.colors.whiteAdvantage
        : theme.colors.blackAdvantage);

      // Classification colour ONLY when this ply belongs to the perspective
      // player; otherwise fall back to the zone-based side colour.
      var isWhiteMove = (p.ply % 2) === 1;
      var isPerspectiveMove = perspective === "white" ? isWhiteMove : !isWhiteMove;
      if (isPerspectiveMove && p.cls) {
        delta.push(resolveAnnotationColor(p.cls));
      } else {
        delta.push(p.display <= 0
          ? theme.colors.whiteAdvantage
          : theme.colors.blackAdvantage);
      }
      prevDisplay = p.display;
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
    var bottomFill = perspective === "white"
      ? theme.colors.whiteAdvantage
      : theme.colors.blackAdvantage;
    var topFill = perspective === "white"
      ? theme.colors.blackAdvantage
      : theme.colors.whiteAdvantage;
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
    var colors = buildSegmentColors(perspective);
    return [
      {
        x: plies,
        y: baseY,
        type: "bar",
        marker: { color: colors.base, opacity: 0.55 },
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
          return [
            p.san,
            p.cp >= 0 ? "+" : "",
            Math.abs(p.cp / 100).toFixed(2),
            dsign,
            Math.abs(cpDelta).toFixed(2),
          ];
        }),
        hovertemplate:
          "Ply %{x}: %{customdata[0]} " +
          "(eval %{customdata[1]}%{customdata[2]} · " +
          "Δ %{customdata[3]}%{customdata[4]})<extra></extra>",
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
    var tickvals = [-1200, -600, 0, 600, 1200];
    var ticktext = tickvals.map(function (v) {
      if (v === 0) return "0";
      var sign = v > 0 ? "+" : "-";
      return sign + (Math.abs(v) / 100);
    });
    return {
      xaxis: { title: { text: "Ply", font: monoFont }, zeroline: false, showgrid: false, tickfont: monoFont },
      yaxis: {
        zeroline: true, zerolinecolor: theme.colors.textBold,
        showgrid: false,
        tickfont: monoFont,
        tickvals: tickvals,
        ticktext: ticktext,
      },
      margin: { l: 36, r: 8, t: 20, b: 60 },
      height: chartHeight,
      paper_bgcolor: "rgba(0,0,0,0)",
      // Cream-toned plot background — same tint as the LC0 chart's draw
      // band so the two charts read as a set. Dark enough that the white
      // advantage bars contrast against it (#216).
      plot_bgcolor: theme.colors.wdlDraw,
      font: { color: theme.colors.text, family: theme.fonts.serif },
      hovermode: "x unified",
      barmode: "relative",
      bargap: 0,
      hoverlabel: {
        bgcolor: "white", bordercolor: theme.colors.textBold,
        font: { color: theme.colors.textBold, family: theme.fonts.mono, size: 12 },
      },
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

  // Trace order: 0 = base (previous score), 1 = delta (this move's change),
  // 2 = ply highlight marker.
  Plotly.newPlot(
    div,
    buildTraces(currentPerspective).concat([highlight]),
    buildLayout(currentPerspective),
    { displaylogo: false, responsive: true }
  ).then(function () {
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
        // Restyle base (0) and delta (1) bar traces in lock-step. Both y
        // values AND colours flip with perspective: the zone-based light/
        // dark assignment tracks the perspective player.
        Plotly.restyle(div, {
          x: [traces[0].x, traces[1].x],
          y: [traces[0].y, traces[1].y],
          "marker.color": [traces[0].marker.color, traces[1].marker.color],
        }, [0, 1]);
        Plotly.restyle(div, {
          customdata: [traces[1].customdata],
        }, [1]);
        Plotly.relayout(div, buildLayout(currentPerspective));
      }
    });
  });
})();
