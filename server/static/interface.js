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
    showReading();
  });
})();

// Covers a wait for the server: the analysis inside the upload post, and the issue step on page 3.
let readingTimer = null;
function showReading() {
  const screen = document.querySelector('[data-reading]');
  if (!screen || readingTimer) return;
  screen.hidden = false;
  const tips = [...screen.querySelectorAll('.reading-tips span')];
  let index = 0;
  readingTimer = setInterval(() => {
    tips[index].classList.remove('is-shown');
    index = (index + 1) % tips.length;
    tips[index].classList.add('is-shown');
  }, 2600);
}
function hideReading() {
  const screen = document.querySelector('[data-reading]');
  if (!screen) return;
  clearInterval(readingTimer);
  readingTimer = null;
  screen.hidden = true;
}
// Coming back with the browser's back button restores the page as it was left; hide the screen again.
window.addEventListener('pageshow', event => {
  if (event.persisted) hideReading();
});
if (!document.querySelector('[data-reading]')?.hidden) showReading();  // Drawn open by the server; start the tips.

(() => {
  const box = document.querySelector('[data-latest]');
  if (!box) return;
  const start = document.getElementById('latest-start');
  start.addEventListener('submit', event => {
    // Block a second start while the first one is analyzed; disabling the button would drop its value.
    if (start.dataset.sent) return event.preventDefault();
    start.dataset.sent = '1';
    event.submitter.textContent = start.dataset.busy;
    showReading();
  });
  // Loaded after the page, so a slow briefing API never holds up the upload form.
  fetch(box.dataset.url, {credentials: 'same-origin'})
    .then(response => response.ok ? response.text() : '')
    .then(html => {
      box.innerHTML = html;
      const slider = box.querySelector('[data-latest-slider]');
      if (slider) slide(slider);
    })
    .catch(() => {});

  function slide(slider) {
    const track = slider.querySelector('.latest-track');
    const slides = [...slider.querySelectorAll('[data-slide]')];
    const dots = [...slider.querySelectorAll('[data-dot]')];
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let index = 0;
    function open(slide, show) {
      slide.querySelector('[data-open]').setAttribute('aria-expanded', show);
      slide.querySelector('.latest-detail').hidden = !show;
    }
    function go(next) {
      slides.forEach(slide => open(slide, false));
      index = (next + slides.length) % slides.length;
      track.style.transform = `translateX(${-100 * index}%)`;
      slides.forEach((slide, i) => {slide.inert = i !== index;});  // Off-screen cards stay out of the tab order.
      dots.forEach((dot, i) => dot.setAttribute('aria-current', i === index));
    }
    slider.addEventListener('click', event => {
      const card = event.target.closest('[data-open]');
      if (card) open(card.closest('[data-slide]'), card.getAttribute('aria-expanded') !== 'true');
      if (event.target.closest('[data-close]')) open(event.target.closest('[data-slide]'), false);
      const dot = event.target.closest('[data-dot]');
      if (dot) go(dots.indexOf(dot));
    });
    go(0);
    if (still || slides.length < 2) return;
    setInterval(() => {
      // Pointing at it, moving through it by keyboard, or reading an opened card holds the slide where it is.
      if (!slider.matches(':hover') && !slider.querySelector(':focus-visible, [aria-expanded="true"]')) go(index + 1);
    }, 4000);
  }
})();

(() => {
  // Going back to the upload step leaves this review behind, so ask first.
  const link = document.querySelector('[data-leave]');
  const dialog = link && document.getElementById(link.dataset.leave);
  if (!dialog?.showModal) return;
  link.addEventListener('click', event => {
    event.preventDefault();
    dialog.showModal();
  });
  dialog.addEventListener('click', event => {
    // A click on the backdrop targets the dialog too, so tell it from the dialog's own padding by position.
    const box = dialog.getBoundingClientRect();
    const outside = event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom;
    if (event.target === dialog && outside) dialog.close('stay');
  });
  dialog.addEventListener('close', () => {
    if (dialog.returnValue === 'leave') window.location.assign(link.href);
  });
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
