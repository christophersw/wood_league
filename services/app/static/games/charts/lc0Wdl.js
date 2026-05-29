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
//   2026-05-29 (#226): book-move strip cells use neutral book colour + opening tooltip.

(function () {
  var rawPayload = JSON.parse(document.getElementById("lc0-wdl-data").textContent || "null");
  var div = document.getElementById("lc0-wdl-chart");
  if (!div || !rawPayload || typeof Plotly === "undefined") return;

  var white = window.ANALYSIS_DATA ? window.ANALYSIS_DATA.white : "";
  var black = window.ANALYSIS_DATA ? window.ANALYSIS_DATA.black : "";
  var openingName = div.getAttribute("data-opening-name") || "";

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
    // Rich per-ply customdata shared by all three band traces: [player, san,
    // bottomLabel, bottom%, draw%, topLabel, top%]. Each band's hovertemplate
    // shows the full WDL state so any hover lands on the same content.
    var customdata = rawPayload.map(function (d, i) {
      var ply = Number(d.ply);
      var isWhiteMove = (ply % 2) === 1;
      var player = isWhiteMove ? white : black;
      return [
        player,
        d.san || "",
        bottomLabel,
        bottomWins[i].toFixed(1),
        draws[i].toFixed(1),
        topLabel,
        topWins[i].toFixed(1),
      ];
    });
    var richTemplate =
      "<b>%{customdata[0]} played %{customdata[1]}</b><br>" +
      "%{customdata[2]}: %{customdata[3]}%<br>" +
      "Draw: %{customdata[4]}%<br>" +
      "%{customdata[5]}: %{customdata[6]}%<extra></extra>";
    return [
      {
        x: plies, y: bottomWins, name: bottomLabel,
        type: "scatter", mode: "lines", stackgroup: "wdl",
        fill: "tozeroy", fillcolor: bottomFill,
        line: { color: bottomLine, width: 1.5 },
        customdata: customdata,
        hovertemplate: richTemplate,
      },
      {
        x: plies, y: draws, name: "Draw",
        type: "scatter", mode: "lines", stackgroup: "wdl",
        fill: "tonexty", fillcolor: DRAW_FILL,
        line: { color: DRAW_LINE, width: 1 },
        customdata: customdata,
        hovertemplate: richTemplate,
      },
      {
        x: plies, y: topWins, name: topLabel,
        type: "scatter", mode: "lines", stackgroup: "wdl",
        fill: "tonexty", fillcolor: topFill,
        line: { color: topLine, width: 1.5 },
        customdata: customdata,
        hovertemplate: richTemplate,
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
        zeroline: false, gridcolor: theme.colors.grid,
        showticklabels: false,
      },
      yaxis: {
        title: { text: "Win / Draw / Loss (%)", font: monoFont },
        range: [0, 100], ticksuffix: "%",
        gridcolor: theme.colors.grid, tickfont: monoFont,
      },
      showlegend: false,
      margin: { l: 36, r: 8, t: 20, b: 12 },
      height: chartHeight,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: theme.colors.plotBg,
      font: { color: theme.colors.text, family: theme.fonts.serif },
      // "closest" so each tooltip is fully owned by its hovertemplate —
      // the "ply N" unified header is gone in favour of "PlayerName played
      // SAN" baked into the band hovertext.
      hovermode: "closest",
      // Hover label styled to match the site's .card-pop tooltips:
      // cream background, ebony border + text, EB Garamond serif body.
      hoverlabel: {
        bgcolor: "#FAF7F0",
        bordercolor: theme.colors.textBold,
        font: { color: theme.colors.textBold, family: theme.fonts.serif, size: 13 },
        align: "left",
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

  /**
   * Build a scatter trace of draw-character markers at plies that carry a
   * non-empty `draw_character` (missed_win / losing_blunder / risky /
   * simplification). Hover shows the character name and its description.
   * Plies without a draw character are omitted from the trace.
   */
  /** Draw-character → CSS-variable hex from the retired chip palette. */
  var DC_COLORS = {
    missed_win: "#D63030",      // --color-vermilion-bright
    losing_blunder: "#E08020",  // --color-ember
    risky: "#F0C040",           // --color-saffron
    simplification: "#5DA12A",  // --color-emerald
  };
  function resolveDcColor(dc) {
    return DC_COLORS[dc] || theme.colors.barDefault;
  }

  var DC_LABEL = {
    missed_win: "Missed Win<br>Let winning chances slip into a draw.",
    losing_blunder: "Losing Blunder<br>Sharpened the position into something decisive.",
    risky: "Risky<br>About as good, but avoidably sharpened.",
    simplification: "Simplification<br>About as good, traded tension for calm.",
  };

  /**
   * Build the draw-character marker trace for the given perspective. Only
   * plies belonging to the perspective player are shown; dots are solid
   * and coloured by the move-quality classification.
   */
  function buildDrawCharacterTrace(perspective) {
    var rows = rawPayload.filter(function (d) {
      if (!d.draw_character) return false;
      var isWhiteMove = (Number(d.ply) % 2) === 1;
      return perspective === "white" ? isWhiteMove : !isWhiteMove;
    });
    return {
      x: rows.map(function (d) { return Number(d.ply); }),
      y: rows.map(function () { return 50; }),
      customdata: rows.map(function (d) {
        var ply = Number(d.ply);
        var isWhiteMove = (ply % 2) === 1;
        var player = isWhiteMove ? white : black;
        return [
          player,
          d.san || "",
          DC_LABEL[d.draw_character] || d.draw_character,
        ];
      }),
      mode: "markers",
      type: "scatter",
      showlegend: false,
      marker: {
        size: 12,
        color: rows.map(function (d) { return resolveDcColor(d.draw_character); }),
      },
      hovertemplate:
        "<b>%{customdata[0]} played %{customdata[1]}</b><br>" +
        "%{customdata[2]}<extra></extra>",
      name: "Draw character",
    };
  }

  var currentPerspective = WoodLeagueAnalysis.getState().perspective;
  var initTraces = buildTraces(currentPerspective).concat([
    highlight,
    buildDrawCharacterTrace(currentPerspective),
  ]);

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
            customdata: [
              newTraces[0].customdata,
              newTraces[1].customdata,
              newTraces[2].customdata,
            ],
            hovertemplate: [
              newTraces[0].hovertemplate,
              newTraces[1].hovertemplate,
              newTraces[2].hovertemplate,
            ],
          }, [0, 1, 2]);

          // Rebuild the draw-character marker trace (trace 4). Plies in the
          // trace differ between perspectives, so the array length can
          // change — delete + add is more reliable than restyle here.
          Plotly.deleteTraces(div, [4]).then(function () {
            return Plotly.addTraces(div, buildDrawCharacterTrace(currentPerspective));
          });
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
          var isBook = !!d.book;
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
          cells.push({ el: cell, ply: ply, cls: cls, book: isBook });
        });

        // Paint cells given a perspective. Only the perspective player's
        // plies carry their classification colour; the rest fall back to
        // the neutral `.cls-cell--unclassified` style. Ply parity: odd =
        // White's move, even = Black's.
        function paintStrip(perspective) {
          cells.forEach(function (c) {
            var isWhiteMove = (c.ply % 2) === 1;
            var isPerspectiveMove = perspective === "white" ? isWhiteMove : !isWhiteMove;
            if (c.book) {
              // Book moves: neutral slate colour, no quality classification, opening tooltip.
              c.el.className = "cls-cell cls-cell--book";
              c.el.style.backgroundColor = window.WoodLeagueChartTheme.colors.book;
              c.el.title = openingName ? "Book — " + openingName : "Book move";
            } else {
              c.el.style.backgroundColor = "";
              c.el.className = "cls-cell" + (
                isPerspectiveMove && c.cls
                  ? " move-annotation-" + c.cls
                  : " cls-cell--unclassified"
              );
            }
          });
          var labelEl = document.getElementById("lc0-wdl-cls-strip-label");
          if (labelEl) {
            var name = perspective === "white" ? white : black;
            labelEl.textContent = name + "'s move quality and key moments";
          }
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
