// Title: winpct.js — Win-for-White headline chart
// Description:
//   Renders a Plotly line chart comparing Stockfish Win% (Lichess logistic)
//   against LC0 Win% (wdl_mu * 100) on a single 0-100% axis. Supports
//   perspective flipping (white/black) and click-to-set-ply via WoodLeagueAnalysis.
//
// Changelog:
//   2026-05-21 (#186): Initial implementation.

(function () {
  var payload = JSON.parse(document.getElementById("winpct-data").textContent || "{}");
  var div = document.getElementById("winpct-chart");
  if (!div || typeof Plotly === "undefined") return;

  var theme = window.WoodLeagueChartTheme;

  /**
   * Build Plotly trace array for the given perspective.
   *
   * Params:
   *   perspective (string): "white" or "black". When "black", the y-axis is
   *     mirrored around 50 so it reads as Win-for-Black.
   *
   * Returns:
   *   Array of three Plotly trace objects: SF line, LC0 line, ply marker.
   */
  function traces(perspective) {
    var sign = perspective === "white" ? 1 : -1;
    function flip(p) { return 50 + sign * (p - 50); }
    return [
      {
        x: payload.sf.map(function (p) { return p.ply; }),
        y: payload.sf.map(function (p) { return flip(p.winpct); }),
        type: "scatter",
        mode: "lines+markers",
        name: "Stockfish",
        line: { color: theme.colors.sf, width: 2 },
      },
      {
        x: payload.lc0.map(function (p) { return p.ply; }),
        y: payload.lc0.map(function (p) { return flip(p.winpct); }),
        type: "scatter",
        mode: "lines+markers",
        name: "LC0",
        line: { color: theme.colors.lc0, width: 2 },
      },
      {
        x: [null, null],
        y: [0, 100],
        mode: "lines",
        showlegend: false,
        hoverinfo: "skip",
        line: { color: theme.colors.highlight, width: 2, dash: "dot" },
      },
    ];
  }

  var layout = {
    yaxis: { range: [0, 100], ticksuffix: "%", title: "Win-for-White" },
    xaxis: { title: "Ply" },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: theme.colors.plotBg,
    font: { color: theme.colors.text, family: theme.fonts.serif },
    height: 280,
    margin: { l: 55, r: 20, t: 20, b: 40 },
    legend: { orientation: "h", y: -0.25 },
    hovermode: "x unified",
  };

  var perspective = WoodLeagueAnalysis.getState().perspective;
  Plotly.newPlot(div, traces(perspective), layout, { displaylogo: false, responsive: true }).then(function () {
    /**
     * Click on a point to jump the shared ply state to that ply.
     */
    div.on("plotly_click", function (ev) {
      if (ev.points && ev.points.length) {
        WoodLeagueAnalysis.setPly(ev.points[0].x);
      }
    });

    /**
     * Subscribe to shared WoodLeagueAnalysis state changes to update the ply
     * marker and re-render traces when the perspective flips.
     *
     * Params:
     *   state (object): { ply: number, perspective: string }
     */
    WoodLeagueAnalysis.subscribe(function (state) {
      // Move the ply marker (trace index 2) to the current ply.
      Plotly.restyle(div, { x: [[state.ply, state.ply]], y: [[0, 100]] }, [2]);

      // Re-render SF and LC0 traces when perspective changes.
      if (state.perspective !== perspective) {
        perspective = state.perspective;
        var t = traces(perspective);
        Plotly.restyle(div, { y: [t[0].y, t[1].y] }, [0, 1]);
      }
    });
  });
})();
