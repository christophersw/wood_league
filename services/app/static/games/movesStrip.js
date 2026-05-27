/**
 * Title: movesStrip.js — Main-board moves strip behavior wiring
 * Description:
 *   Wires click + ply-sync + active-chip auto-scroll + per-engine source
 *   toggling onto the server-rendered moves strip (#pgn-moves) below the
 *   main board. The chip DOM is built server-side by partials/_pgn_table.html;
 *   this module only attaches behavior.
 *
 *   Loaded ONCE from analysis.html's extra_js block (NOT from the HTMX-loaded
 *   partial) so it runs at page-parse time with WoodLeagueAnalysis already
 *   defined. Uses document-level event delegation so the wiring survives any
 *   DOM mount timing (HTMX 2's partial-script execution can race against
 *   swap settle; document-level delegation sidesteps the race entirely).
 *
 *   Per-engine source: each chip carries data-sf-cls and data-lc0-cls plus
 *   both .moves-badge--sf and .moves-badge--lc0 spans. applyEngineSource()
 *   reads the board arrow-toggle state (#board-sf-toggle / #board-lc0-toggle)
 *   and writes the matching .moves-source--{sf,lc0} class on the strip plus
 *   the active engine's move-annotation-{cls} class on each chip. Default is
 *   SF (both toggles on → SF; only LC0 on → LC0; neither on → SF as fallback).
 *
 *   Honors prefers-reduced-motion by falling back to instant scrollIntoView.
 *
 * Changelog:
 *   2026-05-26 (#212 v3): renamed from pgnTable.js (cache-bust); added
 *                     per-engine source toggling synced to the board arrow
 *                     filters.
 *   2026-05-26 (#212 v2): switched to document-level delegation + page-shell
 *                     loading so click + ply-sync work regardless of when
 *                     the partial mounts.
 *   2026-05-26 (#212): rewritten — server-rendered chip strip replaces the
 *                     two-column <details> table; no DOM construction here.
 *   2026-05-21 (#186): Task 14 — lifted from inline analysis.html into module.
 */
(function () {
  "use strict";

  var STRIP_ID = "pgn-moves";
  var CHIP_SELECTOR = "#" + STRIP_ID + " .moves-mv[data-ply]";
  var ALL_CLS_CLASSES = [
    "move-annotation-brilliant", "move-annotation-best", "move-annotation-great",
    "move-annotation-excellent", "move-annotation-good", "move-annotation-inaccuracy",
    "move-annotation-mistake", "move-annotation-blunder",
    "moves-mv--unanalyzed",
  ];

  var prefersReducedMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /**
   * Resolve which engine's classifications should drive the chip top-bar +
   * badge right now, based on the board arrow-toggle state.
   *
   * Rules: SF on (or both on) → SF; only LC0 on → LC0; neither on → SF.
   *
   * @returns {string} "sf" or "lc0".
   */
  function activeEngine() {
    var sf = document.getElementById("board-sf-toggle");
    var lc0 = document.getElementById("board-lc0-toggle");
    var sfOn = sf ? sf.checked : true;
    var lc0On = lc0 ? lc0.checked : true;
    if (sfOn) return "sf";
    if (lc0On) return "lc0";
    return "sf";
  }

  /**
   * Apply the active engine's classification to every chip: swap the chip's
   * move-annotation-{cls} class and flip the strip-level .moves-source--{sf,lc0}
   * class so CSS reveals the matching badge variant. Also updates the summary
   * line's "(showing X move quality)" engine name (#212 v4 live-review item 1).
   */
  function applyEngineSource() {
    var strip = document.getElementById(STRIP_ID);
    if (!strip) return;
    var engine = activeEngine();
    strip.classList.toggle("moves-source--sf", engine === "sf");
    strip.classList.toggle("moves-source--lc0", engine === "lc0");

    // Update the panel summary's engine name span (e.g. "SF" → "LC0").
    var label = document.querySelector("#pgn-panel .moves-engine-name");
    if (label) label.textContent = engine === "sf" ? "SF" : "LC0";

    var attr = engine === "sf" ? "sfCls" : "lc0Cls";
    strip.querySelectorAll(".moves-mv").forEach(function (chip) {
      // Drop all classification classes, then add the active one (or the
      // unanalyzed fallback if this engine has no row at this ply).
      ALL_CLS_CLASSES.forEach(function (c) { chip.classList.remove(c); });
      var cls = chip.dataset[attr] || "";
      if (cls) {
        chip.classList.add("move-annotation-" + cls);
      } else {
        chip.classList.add("moves-mv--unanalyzed");
      }
    });
  }

  // Document-level click delegation: the chip may not exist at script-load
  // time (HTMX swaps the partial in after page parse), but the listener will
  // catch any future click that bubbles up from a .moves-mv chip.
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
   * if the bus isn't initialised yet.
   */
  function subscribeWhenReady() {
    if (window.WoodLeagueAnalysis && typeof window.WoodLeagueAnalysis.subscribe === "function") {
      window.WoodLeagueAnalysis.subscribe(function (state) {
        renderActive(state.ply);
      });
      if (typeof window.WoodLeagueAnalysis.getState === "function") {
        renderActive(window.WoodLeagueAnalysis.getState().ply);
      }
      return;
    }
    setTimeout(subscribeWhenReady, 50);
  }
  subscribeWhenReady();

  // Re-paint active class + engine source whenever HTMX swaps a chip strip in
  // (e.g. on first load, or after a perspective flip if the partial re-mounts).
  document.body.addEventListener("htmx:afterSettle", function (event) {
    if (!event.target || typeof event.target.querySelector !== "function") return;
    if (event.target.querySelector("#" + STRIP_ID) || event.target.id === STRIP_ID) {
      applyEngineSource();
      if (window.WoodLeagueAnalysis && typeof window.WoodLeagueAnalysis.getState === "function") {
        renderActive(window.WoodLeagueAnalysis.getState().ply);
      }
    }
  });

  // Sync chip top-bar + badge whenever the board arrow toggles change. The
  // toggles' onchange already calls window.boardApplyArrowVisibility(); this
  // listener doesn't depend on that — it reacts to the native change event.
  document.addEventListener("change", function (event) {
    if (!event.target || (event.target.id !== "board-sf-toggle" &&
                          event.target.id !== "board-lc0-toggle")) return;
    applyEngineSource();
  });
})();
