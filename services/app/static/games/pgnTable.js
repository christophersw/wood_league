/**
 * Title: pgnTable.js — PGN move-table renderer and ply-sync subscriber
 * Description:
 *   Reads the JSON payload injected by Django's json_script filter
 *   (element id="pgn-moves-data"), builds one table row per move pair into
 *   #pgn-tbody, and subscribes to the WoodLeagueAnalysis ply-state bus so
 *   the active move cell is highlighted and scrolled into view on every ply
 *   change.  Clicking any move cell calls WoodLeagueAnalysis.setPly() to
 *   synchronise the board and all other partials.
 *
 *   Annotation symbols and titles are consumed from window.WoodLeagueMoveAnnotations,
 *   which is defined by the shell template's extra_js block.
 *
 * Changelog:
 *   2026-05-21 (#186): Task 14 — lifted from inline analysis.html into standalone module.
 */
(function () {
  "use strict";

  /**
   * Return an HTML string for a move annotation badge.
   *
   * @param {string|null} classification - The SF move classification label
   *   (e.g. "brilliant", "blunder", "mistake").  May be null or empty.
   * @returns {string} An HTML <span> badge, or an empty string if no symbol
   *   is registered for this classification.
   */
  function annotationHtml(classification) {
    var annotationConfig = window.WoodLeagueMoveAnnotations || { symbols: {}, titles: {} };
    var normalized = (classification || "").toLowerCase();
    var symbol = annotationConfig.symbols[normalized];
    if (!symbol) {
      return "";
    }
    var title = annotationConfig.titles[normalized] || classification;
    return (
      '<span class="move-annotation move-annotation-' +
      normalized +
      '" title="' +
      title +
      '">' +
      symbol +
      "</span>"
    );
  }

  /**
   * Build a single move <td> cell element.
   *
   * @param {{ ply: number, san: string, classification: string|null }} move -
   *   Move data object from the pgn-moves-data payload.
   * @returns {HTMLTableCellElement} A <td> containing the SAN text and an
   *   annotation badge, wired with an onclick that calls setPly.
   */
  function makeCell(move) {
    var td = document.createElement("td");
    td.className = "move-list-cell";
    td.dataset.ply = move.ply;
    td.innerHTML =
      '<span class="move-san">' + move.san + "</span>" +
      annotationHtml(move.classification);
    td.onclick = function () {
      WoodLeagueAnalysis.setPly(parseInt(this.dataset.ply, 10));
    };
    return td;
  }

  /**
   * Populate #pgn-tbody with one <tr> per white/black move pair and wire up
   * the WoodLeagueAnalysis subscriber for active-ply highlighting.
   *
   * The function is idempotent: it clears tbody before inserting rows so
   * HTMX can re-trigger this script after a swap without duplicating rows.
   *
   * @returns {void}
   */
  function init() {
    var dataEl = document.getElementById("pgn-moves-data");
    if (!dataEl) {
      return;
    }
    var moves = JSON.parse(dataEl.textContent || "null") || [];
    var tbody = document.getElementById("pgn-tbody");
    if (!tbody) {
      return;
    }

    // Clear any previously rendered rows (idempotency for HTMX re-swaps).
    tbody.innerHTML = "";

    // Index all moves by ply for quick black-move lookup.
    var rowsByPly = {};
    moves.forEach(function (m) {
      rowsByPly[m.ply] = m;
    });

    // One <tr> per white move; append the paired black move in the same row.
    var whiteMoves = moves.filter(function (m) {
      return m.color === "white";
    });
    whiteMoves.forEach(function (wm) {
      var bm = rowsByPly[wm.ply + 1];
      var tr = document.createElement("tr");
      tr.className = "move-list-row";

      var numTd = document.createElement("td");
      numTd.className = "move-list-number";
      numTd.textContent = wm.move_number + ".";
      tr.appendChild(numTd);
      tr.appendChild(makeCell(wm));

      if (bm) {
        tr.appendChild(makeCell(bm));
      } else {
        var emptyTd = document.createElement("td");
        emptyTd.className = "move-list-cell move-list-cell-empty";
        tr.appendChild(emptyTd);
      }
      tbody.appendChild(tr);
    });

    // Subscribe to ply changes: highlight the active cell and scroll it into view.
    WoodLeagueAnalysis.subscribe(function (state) {
      tbody.querySelectorAll(".move-list-cell[data-ply]").forEach(function (td) {
        var active = parseInt(td.dataset.ply, 10) === state.ply;
        td.classList.toggle("is-active", active);
        if (active) {
          td.scrollIntoView({ block: "nearest", behavior: "smooth" });
        }
      });
    });
  }

  init();
})();
