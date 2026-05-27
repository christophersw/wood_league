/**
 * Title: pgnTable.js — Main-board moves strip behavior wiring
 * Description:
 *   Wires click + ply-sync + active-chip auto-scroll behavior onto the
 *   server-rendered moves strip (#pgn-moves) below the main board. The
 *   chip DOM is built server-side by partials/_pgn_table.html; this module
 *   only attaches behavior.
 *
 *   Loaded ONCE from analysis.html's extra_js block (not from inside the
 *   HTMX-loaded partial) so it runs at page-parse time with WoodLeagueAnalysis
 *   already defined. Uses document-level event delegation and a per-tick
 *   querySelectorAll inside the subscriber so the wiring survives any DOM
 *   mount timing (HTMX 2's partial-script execution can race against swap
 *   settle; document-level delegation sidesteps the race entirely).
 *
 *   Honors prefers-reduced-motion by falling back to instant scrollIntoView.
 *
 * Changelog:
 *   2026-05-26 (#212 v2): switched to document-level delegation + page-shell
 *                     loading so click + ply-sync work regardless of when
 *                     the partial mounts. Dropped data-moves-wired marker
 *                     (no longer needed — single subscription at load).
 *   2026-05-26 (#212): rewritten — server-rendered chip strip replaces the
 *                     two-column <details> table; no DOM construction here.
 *   2026-05-21 (#186): Task 14 — lifted from inline analysis.html into module.
 */
(function () {
  "use strict";

  var STRIP_ID = "pgn-moves";
  var CHIP_SELECTOR = "#" + STRIP_ID + " .moves-mv[data-ply]";

  var prefersReducedMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Document-level click delegation: chip may not exist at script-load time
  // (HTMX swaps the partial in after page parse), but the listener will catch
  // any future click that bubbles up from a .moves-mv chip.
  document.addEventListener("click", function (event) {
    var chip = event.target.closest(CHIP_SELECTOR);
    if (!chip) return;
    var ply = parseInt(chip.dataset.ply, 10);
    if (isNaN(ply)) return;
    if (window.WoodLeagueAnalysis && typeof window.WoodLeagueAnalysis.setPly === "function") {
      window.WoodLeagueAnalysis.setPly(ply);
    }
  });

  /**
   * Apply the .is-active class to the chip matching the given ply and clear
   * it from any other chip. Scrolls the active chip into view inside the
   * bounded-scroll strip.
   *
   * @param {number} ply - The current ply state from WoodLeagueAnalysis.
   */
  function renderActive(ply) {
    var chips = document.querySelectorAll(CHIP_SELECTOR);
    if (!chips.length) return;
    chips.forEach(function (chip) {
      var active = parseInt(chip.dataset.ply, 10) === ply;
      chip.classList.toggle("is-active", active);
      if (active) {
        chip.scrollIntoView({
          block: "nearest",
          behavior: prefersReducedMotion ? "auto" : "smooth",
        });
      }
    });
  }

  /**
   * Subscribe to WoodLeagueAnalysis if available; defer (and retry briefly)
   * if the bus isn't initialised yet. analysis.html loads plySync.js before
   * this module in extra_js, so the bus is normally present immediately,
   * but the retry handles unusual load orders gracefully.
   */
  function subscribeWhenReady() {
    if (window.WoodLeagueAnalysis && typeof window.WoodLeagueAnalysis.subscribe === "function") {
      window.WoodLeagueAnalysis.subscribe(function (state) {
        renderActive(state.ply);
      });
      // Render once immediately to highlight whatever ply the bus starts on
      // even if the chip strip mounted before the first state tick.
      if (typeof window.WoodLeagueAnalysis.getState === "function") {
        renderActive(window.WoodLeagueAnalysis.getState().ply);
      }
      return;
    }
    setTimeout(subscribeWhenReady, 50);
  }
  subscribeWhenReady();

  // Re-paint active class whenever HTMX swaps a chip strip in (e.g. on first
  // load, or after a perspective flip if the partial gets re-requested).
  document.body.addEventListener("htmx:afterSettle", function (event) {
    if (!event.target || typeof event.target.querySelector !== "function") return;
    if (event.target.querySelector("#" + STRIP_ID) || event.target.id === STRIP_ID) {
      if (window.WoodLeagueAnalysis && typeof window.WoodLeagueAnalysis.getState === "function") {
        renderActive(window.WoodLeagueAnalysis.getState().ply);
      }
    }
  });
})();
