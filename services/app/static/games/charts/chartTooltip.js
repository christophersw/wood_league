// Title: chartTooltip.js — Chart info-tooltip close behavior
// Description:
//   Close any open chart info tooltip when a different one opens,
//   or when the user clicks outside all open tooltips. Scoped to
//   <details class="chart-info-tooltip"> elements.
//   Mirrors cardTooltip.js behavior for the chart section.
//
// Changelog:
//   2026-05-21 (#186): Initial implementation (replaces Task 4 placeholder).

(function () {
  document.addEventListener("click", function (e) {
    document.querySelectorAll("details.chart-info-tooltip[open]").forEach(function (d) {
      if (!d.contains(e.target)) d.open = false;
    });
  });
})();
