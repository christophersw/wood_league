// Title: chartTheme.js — Single source of truth for chart colors and fonts
// Description:
//   Reads the chart-semantic CSS custom properties defined on :root in
//   static/css/main.css and exposes them on window.WoodLeagueChartTheme so the
//   Plotly chart scripts can stay free of hard-coded hex literals. Any palette
//   change made in main.css automatically propagates to every chart, the cards,
//   and the chip strip — no JS edit required.
//
//   Must be loaded before any chart script (sfCp.js, lc0Wdl.js).
//   Falls back to neutral defaults if a token is missing so the page never
//   renders blank — but a missing token is a bug in main.css.
//
// Changelog:
//   2026-05-21 (#186): Initial.
//   2026-05-27 (#216): Remove winpct.js from comment (chart retired).

(function () {
  function readVar(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  // Each JS key below is a semantic ALIAS for one physical CSS color token.
  // To change a color, edit it in static/css/main.css :root — every chart
  // that uses that token follows. Keys here are read-only at the call site.
  window.WoodLeagueChartTheme = {
    colors: {
      sf:               readVar("--color-tobacco",         "#A8781B"),
      lc0:              readVar("--color-denim",           "#35586F"),
      highlight:        readVar("--color-amber-burnt",     "#C17F24"),
      grid:             readVar("--color-band-grid",       "#EDE0C4"),
      barDefault:       readVar("--color-band",            "#C9B998"),
      plotBg:           readVar("--color-tint-plot",       "rgba(237,224,196,0.2)"),
      whiteAdvantage:   readVar("--color-tint-white",      "rgba(255,255,255,0.98)"),
      whiteLine:        readVar("--color-near-white",      "#F7F7F7"),
      blackAdvantage:   readVar("--color-tint-dark",       "rgba(26,26,26,0.85)"),
      blackLine:        readVar("--color-coal",            "#1A1A1A"),
      text:             readVar("--color-coal-text",       "#1C1C1C"),
      textBold:         readVar("--color-coal",            "#1A1A1A"),
      wdlWin:           readVar("--color-emerald",         "#5DA12A"),
      wdlDraw:          readVar("--color-tint-draw",       "rgba(139,58,42,0.50)"),
      wdlLoss:          readVar("--color-rust",            "#8B3A2A"),
    },
    fonts: {
      mono:  readVar("--font-mono",  "DM Mono,monospace"),
      serif: readVar("--font-serif", "EB Garamond,serif"),
      title: "Georgia,serif",
    },
  };
})();
