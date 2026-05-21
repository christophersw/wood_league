// Title: cardTooltip.js — Card info-tooltip close behavior
// Description:
//   Close any open card info tooltip when a different one opens,
//   or when the user clicks outside all open tooltips. Scoped to
//   <details class="card-info-tooltip"> elements.
//
// Changelog:
//   2026-05-21 (#186): Initial implementation.

(function () {
  document.addEventListener("click", function (e) {
    document.querySelectorAll("details.card-info-tooltip[open]").forEach(function (d) {
      if (!d.contains(e.target)) d.open = false;
    });
  });
})();
