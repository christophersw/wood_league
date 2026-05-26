/**
 * Title: pgnTable.js — Main-board moves strip behavior wiring
 * Description:
 *   Wires click + ply-sync + active-chip auto-scroll behavior onto the
 *   server-rendered moves strip (#pgn-moves) below the main board.  The
 *   chip DOM is built server-side by partials/_pgn_table.html; this module
 *   only attaches a delegated click handler, subscribes to the
 *   WoodLeagueAnalysis ply-state bus, and keeps the active chip visible
 *   inside the bounded-scroll strip via scrollIntoView({block: 'nearest'}).
 *
 *   Honors prefers-reduced-motion by falling back to instant scroll.  The
 *   data-moves-wired marker on the strip prevents double-subscription if
 *   HTMX re-swaps the partial during the page lifetime.
 *
 * Changelog:
 *   2026-05-26 (#212): rewritten — server-rendered chip strip replaces the
 *                     two-column <details> table; no DOM construction here.
 *   2026-05-21 (#186): Task 14 — lifted from inline analysis.html into module.
 */
(function () {
  "use strict";

  function init() {
    var strip = document.getElementById("pgn-moves");
    if (!strip) return;
    if (strip.dataset.movesWired === "1") return;  // guard against HTMX re-swap re-binds
    strip.dataset.movesWired = "1";

    strip.addEventListener("click", function (event) {
      var chip = event.target.closest(".moves-mv[data-ply]");
      if (!chip) return;
      var ply = parseInt(chip.dataset.ply, 10);
      if (isNaN(ply)) return;
      if (window.WoodLeagueAnalysis && typeof window.WoodLeagueAnalysis.setPly === "function") {
        window.WoodLeagueAnalysis.setPly(ply);
      }
    });

    var prefersReducedMotion = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (!window.WoodLeagueAnalysis || typeof window.WoodLeagueAnalysis.subscribe !== "function") {
      return;
    }
    window.WoodLeagueAnalysis.subscribe(function (state) {
      strip.querySelectorAll(".moves-mv[data-ply]").forEach(function (chip) {
        var active = parseInt(chip.dataset.ply, 10) === state.ply;
        chip.classList.toggle("is-active", active);
        if (active) {
          chip.scrollIntoView({
            block: "nearest",
            behavior: prefersReducedMotion ? "auto" : "smooth",
          });
        }
      });
    });
  }

  init();
})();
