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

  var moveQualityColors =
    (window.WoodLeagueMoveAnnotations && window.WoodLeagueMoveAnnotations.colors) || {};
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
   * Build the bar colour array from move-quality class colours.
   *
   * Returns:
   *   Array of CSS colour strings, one per point.
   */
  function buildColors() {
    return rawPoints.map(function (p) {
      return moveQualityColors[p.cls] || theme.colors.barDefault;
    });
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
  function buildTrace(perspective) {
    var pts = getPointsForPerspective(perspective);
    return {
      x: pts.map(function (p) { return p.ply; }),
      y: pts.map(function (p) { return p.display; }),
      type: "bar",
      marker: { color: buildColors() },
      customdata: pts.map(function (p) {
        return [p.san, p.cp >= 0 ? "+" : "", Math.abs(p.cp / 100).toFixed(2)];
      }),
      hovertemplate: "Ply %{x}: %{customdata[0]} %{customdata[1]}%{customdata[2]} pawns<extra></extra>",
      name: "Eval",
      showlegend: false,
    };
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
        showgrid: true, gridcolor: theme.colors.grid,
        tickfont: monoFont,
        tickvals: tickvals,
        ticktext: ticktext,
      },
      margin: { l: 55, r: 20, t: 56, b: 60 },
      height: chartHeight,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: theme.colors.plotBg,
      font: { color: theme.colors.text, family: theme.fonts.serif },
      hovermode: "x unified",
      hoverlabel: {
        bgcolor: "white", bordercolor: theme.colors.textBold,
        font: { color: theme.colors.textBold, family: theme.fonts.mono, size: 12 },
      },
      shapes: buildShapes(perspective),
      annotations: [{
        text: "Stockfish Evaluation",
        xref: "paper", yref: "paper",
        x: 0.5, y: 1.10, xanchor: "center",
        showarrow: false,
        font: { size: 14, color: theme.colors.textBold, family: theme.fonts.title },
      }],
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

  Plotly.newPlot(
    div,
    [buildTrace(currentPerspective), highlight],
    buildLayout(currentPerspective),
    { displaylogo: false, responsive: true }
  ).then(function () {
    /**
     * Click on a bar to jump shared ply state to that ply.
     */
    div.on("plotly_click", function (ev) {
      if (ev.points && ev.points.length) {
        WoodLeagueAnalysis.setPly(ev.points[0].x);
      }
    });

    /**
     * Subscribe to shared WoodLeagueAnalysis state changes.
     * Updates the ply marker and re-renders the chart when perspective flips.
     *
     * Params:
     *   state (object): { ply: number, perspective: string }
     */
    WoodLeagueAnalysis.subscribe(function (state) {
      // Move the ply marker (trace index 1).
      Plotly.restyle(div, { x: [[state.ply, state.ply]], y: [[-DISPLAY_CAP, DISPLAY_CAP]] }, [1]);

      if (state.perspective !== currentPerspective) {
        currentPerspective = state.perspective;
        var pts = getPointsForPerspective(currentPerspective);
        Plotly.restyle(div, {
          x: [pts.map(function (p) { return p.ply; })],
          y: [pts.map(function (p) { return p.display; })],
          customdata: [pts.map(function (p) {
            return [p.san, p.cp >= 0 ? "+" : "", Math.abs(p.cp / 100).toFixed(2)];
          })],
        }, [0]);
        Plotly.relayout(div, buildLayout(currentPerspective));
      }
    });
  });
})();
