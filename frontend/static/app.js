/* Presentation only. All calculations and mutations are handled by the server. */
(() => {
  'use strict';
  const bindChoices = (root = document) => {
    root.querySelectorAll('[data-choice-form]').forEach(form => {
      if (form.dataset.bound) return;
      form.dataset.bound = 'true';
      const control = form.querySelector('[data-choice-control]');
      const update = () => form.querySelectorAll('[data-choice-panel]').forEach(panel => {
        const active = panel.dataset.choicePanel === control.value;
        panel.hidden = !active;
        panel.querySelectorAll('input, select, textarea').forEach(input => { input.disabled = !active; });
      });
      control.addEventListener('change', update);
      update();
    });
  };
  const mobile = window.matchMedia('(max-width: 680px)');
  const syncMenu = () => {
    const open = mobile.matches && document.body.classList.contains('nav-open');
    const sidebar = document.querySelector('#sidebar');
    if (sidebar) {
      sidebar.inert = mobile.matches && !open;
      sidebar.setAttribute('aria-hidden', String(mobile.matches && !open));
    }
    const workspace = document.querySelector('.workspace');
    if (workspace) workspace.inert = open;
    document.querySelector('[data-menu-toggle]')?.setAttribute('aria-expanded', String(open));
  };
  const closeMenu = (restoreFocus = false) => {
    document.body.classList.remove('nav-open');
    syncMenu();
    if (restoreFocus) document.querySelector('[data-menu-toggle]')?.focus();
  };
  document.addEventListener('DOMContentLoaded', () => {
    bindChoices();
    syncMenu();
    mobile.addEventListener('change', () => { if (!mobile.matches) closeMenu(); else syncMenu(); });
    document.querySelector('[data-menu-toggle]')?.addEventListener('click', event => {
      const open = document.body.classList.toggle('nav-open');
      syncMenu();
      if (open) document.querySelector('.sidebar a[aria-current]')?.focus();
    });
    document.querySelector('[data-close-menu]')?.addEventListener('click', () => closeMenu(true));
    document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => {
      const input = document.querySelector('#question');
      input.value = button.dataset.question;
      input.focus();
    }));
  });
  document.addEventListener('keydown', event => {
    if (!document.body.classList.contains('nav-open')) return;
    if (event.key === 'Escape') { closeMenu(true); return; }
    if (event.key === 'Tab') {
      const links = [...document.querySelectorAll('#sidebar a[href]')];
      const first = links[0], last = links[links.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  document.addEventListener('htmx:afterSwap', event => bindChoices(event.detail.target));
  document.addEventListener('htmx:afterRequest', event => {
    const form = event.detail.elt;
    if (event.detail.successful && form.matches?.('[data-reset-on-success]') && !event.detail.xhr.responseText.includes('notice-error')) form.reset();
  });
  const notifyError = () => {
    const host = document.querySelector('#global-notice');
    if (!host) return;
    const note = document.createElement('div');
    note.className = 'notice notice-error';
    note.setAttribute('role', 'alert');
    note.textContent = '暂时无法连接本地助手。确认助手仍在运行后，再试一次。';
    host.replaceChildren(note);
    host.scrollIntoView({ block: 'nearest' });
  };
  document.addEventListener('htmx:sendError', notifyError);
  document.addEventListener('htmx:responseError', notifyError);
})();
