(() => {
  const form = document.querySelector('[data-upload-form]');
  if (!form) return;
  const input = form.querySelector('input[type=file]');
  const zone = form.querySelector('.dropzone');
  const name = form.querySelector('[data-file-name]');
  const status = form.querySelector('[data-upload-status]');
  const idle = name.textContent;
  function showFile() {
    name.textContent = input.files[0]?.name || idle;
  }
  input.addEventListener('change', showFile);
  zone.addEventListener('dragover', event => {event.preventDefault(); zone.classList.add('is-dragging');});
  zone.addEventListener('dragleave', () => zone.classList.remove('is-dragging'));
  zone.addEventListener('drop', event => {
    event.preventDefault();
    zone.classList.remove('is-dragging');
    if (event.dataTransfer.files.length) {
      input.files = event.dataTransfer.files;
      showFile();
    }
  });
  form.addEventListener('submit', event => {
    if (!input.files.length && !form.elements.text.value.trim()) {
      event.preventDefault();
      status.textContent = form.dataset.needInput;
      return;
    }
    const button = form.querySelector('[data-upload-submit]');
    button.disabled = true;
    button.textContent = form.dataset.busy;
    status.textContent = form.dataset.wait;
  });
})();

(() => {
  const dialog = document.querySelector('[data-policy-dialog]');
  if (!dialog) return;
  const list = dialog.querySelector('[data-policy-list]');
  const details = dialog.querySelectorAll('[data-policy-detail]');
  // An empty id goes back to the list; any other id shows that policy's full text.
  function show(id) {
    list.hidden = Boolean(id);
    details.forEach(detail => {detail.hidden = detail.dataset.policyDetail !== id;});
    dialog.scrollTop = 0;
  }
  dialog.addEventListener('click', event => {
    const card = event.target.closest('[data-show]');
    if (card) show(card.dataset.show);
    if (event.target.closest('[data-back]')) show('');
  });
  details.forEach(form => form.addEventListener('submit', event => {
    // Block a second start while the first one is analyzed; disabling the button would drop its value.
    if (form.dataset.sent) return event.preventDefault();
    form.dataset.sent = '1';
    form.querySelector('[data-policy-status]').textContent = form.dataset.busy;
  }));
  // Closing returns to the plain home address, so a reload does not reopen the popup.
  dialog.addEventListener('close', () => history.replaceState(null, '', location.pathname));
  dialog.showModal();
})();

(() => {
  const toggle = document.querySelector('.lang-switch');
  if (!toggle) return;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  toggle.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (!link || link.hasAttribute('aria-current')) return;
    // The server draws the page in the new language, so let the highlight slide first, then follow the link.
    event.preventDefault();
    toggle.dataset.lang = link.lang;
    toggle.querySelector('[aria-current]').removeAttribute('aria-current');
    link.setAttribute('aria-current', 'true');
    setTimeout(() => window.location.assign(link.href), reducedMotion ? 0 : 260);
  });
})();
