/**
 * Title: plySync.js — Shared ply and perspective synchronization
 * Description:
 *   Manages the shared currentPly and perspective state across all move-analysis
 *   elements (board, PGN table, Stockfish chart, Lc0 chart) and syncs the URL
 *   query string. Subscribers register a callback that fires on any state change.
 *
 * Changelog:
 *   2026-05-04 (#16): Created as part of game analysis page rewrite
 */

(function () {
  var _ply = 0;
  var _perspective = "white";
  var _totalPlies = 0;
  var _subscribers = [];

  function _notify() {
    var state = { ply: _ply, perspective: _perspective, totalPlies: _totalPlies };
    for (var i = 0; i < _subscribers.length; i++) {
      try { _subscribers[i](state); } catch (e) { /* ignore subscriber errors */ }
    }
  }

  function _syncUrl() {
    if (!window.history || !window.history.replaceState) return;
    var url = new URL(window.location.href);
    url.searchParams.set("ply", _ply);
    url.searchParams.set("orientation", _perspective);
    window.history.replaceState(null, "", url.toString());
  }

  window.WoodLeagueAnalysis = {
    /**
     * Set the current ply. Clamps to [0, totalPlies], notifies subscribers, syncs URL.
     *
     * @param {number} ply - Target ply index.
     */
    setPly: function (ply) {
      _ply = Math.max(0, Math.min(_totalPlies, parseInt(ply, 10) || 0));
      _syncUrl();
      _notify();
    },

    /**
     * Set the board perspective. Notifies subscribers and syncs URL.
     *
     * @param {string} perspective - "white" or "black".
     */
    setPerspective: function (perspective) {
      if (perspective !== "white" && perspective !== "black") return;
      _perspective = perspective;
      _syncUrl();
      _notify();
    },

    /**
     * Set total number of plies in the game (called by board partial after loading frames).
     *
     * @param {number} total - Total move count.
     */
    setTotalPlies: function (total) {
      _totalPlies = Math.max(0, parseInt(total, 10) || 0);
      _ply = Math.min(_ply, _totalPlies);
      _notify();
    },

    /**
     * Subscribe to state changes. The callback receives {ply, perspective, totalPlies}.
     * Returns an unsubscribe function.
     *
     * @param {function} fn - Callback receiving the current state object.
     * @returns {function} Unsubscribe function.
     */
    subscribe: function (fn) {
      _subscribers.push(fn);
      return function () {
        _subscribers = _subscribers.filter(function (s) { return s !== fn; });
      };
    },

    /**
     * Return a snapshot of the current state.
     *
     * @returns {{ply: number, perspective: string, totalPlies: number}}
     */
    getState: function () {
      return { ply: _ply, perspective: _perspective, totalPlies: _totalPlies };
    },

    /**
     * Initialize ply and perspective from the current URL query string.
     * Falls back to the provided defaults if URL params are absent or invalid.
     *
     * @param {{defaultPly: number, defaultPerspective: string}} opts
     */
    initFromUrl: function (opts) {
      opts = opts || {};
      var params = new URLSearchParams(window.location.search);
      var rawPly = params.get("ply");
      var rawOri = params.get("orientation");
      _ply = rawPly !== null ? Math.max(0, parseInt(rawPly, 10) || 0) : (opts.defaultPly || 0);
      _perspective = (rawOri === "white" || rawOri === "black") ? rawOri : (opts.defaultPerspective || "white");
    },
  };
})();
