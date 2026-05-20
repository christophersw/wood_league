/**
 * Title:       wc_modal.js — Wood League modal controller
 * Description: Vanilla-JS controller for the .wc-modal component.
 *              Open: click [data-wc-modal-open="<id>"] or WcModal.open(id).
 *              Close: .wc-modal__close, backdrop click, Escape, or WcModal.close(id).
 *              HTMX: auto-opens modal when content is swapped into its panel-body.
 *              Emits wc-modal:opened / wc-modal:closed CustomEvents on the modal element.
 * Changelog:
 *   2026-05-20  Initial implementation. Task 9 of #162 search-page rework.
 */
(function () {
  'use strict';

  function open(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.classList.add('wc-modal--open');
    document.body.style.overflow = 'hidden';
    el.dispatchEvent(new CustomEvent('wc-modal:opened', { bubbles: true }));
  }

  function close(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('wc-modal--open');
    document.body.style.overflow = '';
    el.dispatchEvent(new CustomEvent('wc-modal:closed', { bubbles: true }));
  }

  function enclosingModal(el) {
    return el ? el.closest('.wc-modal') : null;
  }

  // Click delegation — open trigger, close button, backdrop
  document.addEventListener('click', function (e) {
    var opener = e.target.closest('[data-wc-modal-open]');
    if (opener) { e.preventDefault(); open(opener.dataset.wcModalOpen); return; }

    var closeBtn = e.target.closest('.wc-modal__close');
    if (closeBtn) { var m = enclosingModal(closeBtn); if (m) close(m.id); return; }

    if (e.target.classList.contains('wc-modal__backdrop')) {
      var modal = enclosingModal(e.target);
      if (modal) close(modal.id);
    }
  });

  // Escape closes the top-most open modal
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var open_modals = document.querySelectorAll('.wc-modal.wc-modal--open');
    if (open_modals.length) close(open_modals[open_modals.length - 1].id);
  });

  // HTMX afterSwap safety net — auto-open if content swapped into a panel-body
  document.addEventListener('htmx:afterSwap', function (e) {
    var modal = enclosingModal(e.target);
    if (modal && !modal.classList.contains('wc-modal--open')) open(modal.id);
  });

  window.WcModal = { open: open, close: close };
})();
