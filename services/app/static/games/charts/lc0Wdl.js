// Title: lc0Wdl.js — LC0 WDL stacked-area chart
// Description:
//   Renders a Plotly stacked-area chart of LC0 WDL probability distribution per ply
//   (wdl_win / wdl_draw / wdl_loss read from White-frame wdl_*_adj columns).
//   Supports perspective-flipping (white/black), click-to-set-ply, and ply-marker
//   synchronisation via WoodLeagueAnalysis shared state.
//   Data is read from the `lc0-wdl-data` JSON-script element emitted by the partial.
//   Player names come from window.ANALYSIS_DATA.white/black set by the shell template.
//
// Changelog:
//   2026-05-21 (#186): Lifted from analysis.html inline script; wired to lc0-wdl-data.
//   2026-05-27 (#216): add per-ply classification strip beneath the WDL area.

(function () {
  var rawPayload = JSON.parse(document.getElementById("lc0-wdl-data").textContent || "null");
  var div = document.getElementById("lc0-wdl-chart");
  if (!div || !rawPayload || typeof Plotly === "undefined") return;

  var white = window.ANALYSIS_DATA ? window.ANALYSIS_DATA.white : "";
  var black = window.ANALYSIS_DATA ? window.ANALYSIS_DATA.black : "";

  var plies = rawPayload.map(function (d) { return Number(d.ply); });

  // Fixed in-card height (#216): chart lives inside the LC0 stat card,
  // with the classification strip directly beneath it.
  var chartHeight = 240;

  var theme = window.WoodLeagueChartTheme;
  var WHITE_FILL = theme.colors.whiteAdvantage;
  var WHITE_LINE = theme.colors.whiteLine;
  var BLACK_FILL = theme.colors.blackAdvantage;
  var BLACK_LINE = theme.colors.blackLine;
  var DRAW_FILL = theme.colors.wdlDraw;
  var DRAW_LINE = theme.colors.wdlLoss;

  /**
   * Build the three Plotly stacked-area traces for the given perspective.
   *
   * In White perspective the bottom band is White wins; in Black perspective the
   * bottom band is Black wins. The draw band is always in the middle.
   *
   * Params:
   *   perspective (string): "white" or "black".
   *
   * Returns:
   *   Array of three Plotly trace objects (type "scatter", stackgroup "wdl").
   */
  function buildTraces(perspective) {
    var isWhite = perspective === "white";
    var bottomWins = rawPayload.map(function (d) {
      return Number(isWhite ? d.wdl_win : d.wdl_loss) / 10;
    });
    var draws = rawPayload.map(function (d) { return Number(d.wdl_draw) / 10; });
    var topWins = rawPayload.map(function (d) {
      return Number(isWhite ? d.wdl_loss : d.wdl_win) / 10;
    });
    var bottomLabel = isWhite ? ("♙ " + white + " Win") : ("♟ " + black + " Win");
    var topLabel = isWhite ? ("♟ " + black + " Win") : ("♙ " + white + " Win");
    var bottomFill = isWhite ? WHITE_FILL : BLACK_FILL;
    var bottomLine = isWhite ? WHITE_LINE : BLACK_LINE;
    var topFill = isWhite ? BLACK_FILL : WHITE_FILL;
    var topLine = isWhite ? BLACK_LINE : WHITE_LINE;
    return [
      {
        x: plies, y: bottomWins, name: bottomLabel,
        type: "scatter", mode: "lines", stackgroup: "wdl",
        fill: "tozeroy", fillcolor: bottomFill,
        line: { color: bottomLine, width: 1.5 },
        hovertemplate: bottomLabel + ": %{y:.1f}%<extra></extra>",
      },
      {
        x: plies, y: draws, name: "Draw",
        type: "scatter", mode: "lines", stackgroup: "wdl",
        fill: "tonexty", fillcolor: DRAW_FILL,
        line: { color: DRAW_LINE, width: 1 },
        hovertemplate: "Draw: %{y:.1f}%<extra></extra>",
      },
      {
        x: plies, y: topWins, name: topLabel,
        type: "scatter", mode: "lines", stackgroup: "wdl",
        fill: "tonexty", fillcolor: topFill,
        line: { color: topLine, width: 1.5 },
        hovertemplate: topLabel + ": %{y:.1f}%<extra></extra>",
      },
    ];
  }

  /**
   * Build the Plotly layout for the WDL stacked-area chart.
   *
   * Returns:
   *   Plotly layout object.
   */
  function buildLayout() {
    var monoFont = { size: 11, color: theme.colors.text, family: theme.fonts.mono };
    return {
      xaxis: {
        title: { text: "Ply", font: monoFont },
        zeroline: false, gridcolor: theme.colors.grid, tickfont: monoFont,
      },
      yaxis: {
        title: { text: "Win / Draw / Loss (%)", font: monoFont },
        range: [0, 100], ticksuffix: "%",
        gridcolor: theme.colors.grid, tickfont: monoFont,
      },
      legend: {
        orientation: "h", y: -0.22,
        font: { color: theme.colors.text, family: theme.fonts.serif, size: 12 },
        bgcolor: "rgba(0,0,0,0)",
      },
      margin: { l: 36, r: 8, t: 20, b: 60 },
      height: chartHeight,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: theme.colors.plotBg,
      font: { color: theme.colors.text, family: theme.fonts.serif },
      hovermode: "x unified",
      hoverlabel: {
        bgcolor: "white", bordercolor: theme.colors.textBold,
        font: { color: theme.colors.textBold, family: theme.fonts.mono, size: 12 },
      },
    };
  }

  /** Vertical dotted line marking the currently selected ply. */
  var highlight = {
    x: [null, null], y: [0, 100],
    mode: "lines",
    showlegend: false,
    hoverinfo: "skip",
    line: { color: theme.colors.highlight, width: 2, dash: "dot" },
  };

  var currentPerspective = WoodLeagueAnalysis.getState().perspective;
  var initTraces = buildTraces(currentPerspective).concat([highlight]);

  Plotly.newPlot(div, initTraces, buildLayout(), { displaylogo: false, responsive: true })
    .then(function () {
      /**
       * Click on the chart to jump shared ply state to that position.
       */
      div.on("plotly_click", function (ev) {
        if (ev.points && ev.points.length) {
          WoodLeagueAnalysis.setPly(ev.points[0].x);
        }
      });

      /**
       * Subscribe to shared WoodLeagueAnalysis state changes.
       * Updates the ply marker and rebuilds traces when perspective flips.
       *
       * Params:
       *   state (object): { ply: number, perspective: string }
       */
      WoodLeagueAnalysis.subscribe(function (state) {
        // Move the ply highlight marker (trace index 3).
        Plotly.restyle(div, { x: [[state.ply, state.ply]], y: [[0, 100]] }, [3]);

        if (state.perspective !== currentPerspective) {
          currentPerspective = state.perspective;
          var newTraces = buildTraces(currentPerspective);
          Plotly.restyle(div, {
            y: [newTraces[0].y, newTraces[1].y, newTraces[2].y],
            name: [newTraces[0].name, newTraces[1].name, newTraces[2].name],
            fillcolor: [newTraces[0].fillcolor, newTraces[1].fillcolor, newTraces[2].fillcolor],
            "line.color": [newTraces[0].line.color, newTraces[1].line.color, newTraces[2].line.color],
            hovertemplate: [
              newTraces[0].hovertemplate,
              newTraces[1].hovertemplate,
              newTraces[2].hovertemplate,
            ],
          }, [0, 1, 2]);
        }
      });

      // Per-ply classification strip (#216) — sibling to the Plotly div,
      // visually integrated with the chart via main.css positioning. Each
      // cell carries its classification class only when its ply belongs to
      // the perspective player; opposing-side cells are neutral so the eye
      // focuses on the player's own quality.
      var stripEl = document.getElementById("lc0-wdl-cls-strip");
      if (stripEl) {
        var sanByPly = {};
        rawPayload.forEach(function (d) { sanByPly[Number(d.ply)] = d.san; });
        var cells = [];
        rawPayload.forEach(function (d) {
          var cls = (d.classification || "").toLowerCase();
          var cell = document.createElement("div");
          var ply = Number(d.ply);
          var humanCls = cls ? cls.charAt(0).toUpperCase() + cls.slice(1) : "—";
          cell.title = "Ply " + ply + " · " + (sanByPly[ply] || "") + " · " + humanCls;
          cell.setAttribute("role", "listitem");
          cell.addEventListener("click", function () {
            if (window.WoodLeagueAnalysis) {
              window.WoodLeagueAnalysis.setPly(ply);
            }
          });
          stripEl.appendChild(cell);
          cells.push({ el: cell, ply: ply, cls: cls });
        });

        // Paint cells given a perspective. Only the perspective player's
        // plies carry their classification colour; the rest fall back to
        // the neutral `.cls-cell--unclassified` style. Ply parity: odd =
        // White's move, even = Black's.
        function paintStrip(perspective) {
          cells.forEach(function (c) {
            var isWhiteMove = (c.ply % 2) === 1;
            var isPerspectiveMove = perspective === "white" ? isWhiteMove : !isWhiteMove;
            c.el.className = "cls-cell" + (
              isPerspectiveMove && c.cls
                ? " move-annotation-" + c.cls
                : " cls-cell--unclassified"
            );
          });
        }
        paintStrip(currentPerspective);
        WoodLeagueAnalysis.subscribe(function (state) {
          if (state.perspective !== stripEl.dataset.lastPerspective) {
            stripEl.dataset.lastPerspective = state.perspective;
            paintStrip(state.perspective);
          }
        });
        stripEl.dataset.lastPerspective = currentPerspective;
      }
    });
})();
