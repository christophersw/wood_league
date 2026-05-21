// Title: chartTheme.js — Single source of truth for chart colors and fonts
// Description:
//   Reads the chart-semantic CSS custom properties defined on :root in
//   static/css/main.css and exposes them on window.WoodLeagueChartTheme so the
//   Plotly chart scripts can stay free of hard-coded hex literals. Any palette
//   change made in main.css automatically propagates to every chart, the cards,
//   and the chip strip — no JS edit required.
//
//   Must be loaded before any chart script (winpct.js, sfCp.js, lc0Wdl.js).
//   Falls back to neutral defaults if a token is missing so the page never
//   renders blank — but a missing token is a bug in main.css.
//
// Changelog:
//   2026-05-21 (#186): Initial.

(function () {
  function readVar(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  window.WoodLeagueChartTheme = {
    colors: {
      sf:               readVar("--color-chart-sf",               "#A8781B"),
      lc0:              readVar("--color-chart-lc0",              "#35586F"),
      highlight:        readVar("--color-chart-highlight",        "#C17F24"),
      grid:             readVar("--color-chart-grid",             "#EDE0C4"),
      barDefault:       readVar("--color-chart-bar-default",      "#C9B998"),
      plotBg:           readVar("--color-chart-plot-bg",          "rgba(237,224,196,0.2)"),
      whiteAdvantage:   readVar("--color-chart-white-advantage",  "rgba(255,255,255,0.98)"),
      whiteLine:        readVar("--color-chart-white-line",       "#F7F7F7"),
      blackAdvantage:   readVar("--color-chart-black-advantage",  "rgba(26,26,26,0.85)"),
      blackLine:        readVar("--color-chart-black-line",       "#1A1A1A"),
      text:             readVar("--color-chart-text",             "#1C1C1C"),
      textBold:         readVar("--color-chart-text-bold",        "#1A1A1A"),
      wdlWin:           readVar("--color-wdl-win",                "#5DA12A"),
      wdlDraw:          readVar("--color-wdl-draw",               "rgba(139,58,42,0.50)"),
      wdlLoss:          readVar("--color-wdl-loss",               "#8B3A2A"),
    },
    fonts: {
      mono:  readVar("--font-mono",  "DM Mono,monospace"),
      serif: readVar("--font-serif", "EB Garamond,serif"),
      title: "Georgia,serif",
    },
  };
})();
