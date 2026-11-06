(() => {
  const form = document.getElementById('review-runner');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const scroll = document.getElementById('chat-scroll');

  function revealReference() {
    const target = document.getElementById(location.hash.slice(1));
    if (!target) return;
    let parent = target.parentElement;
    while (parent) {
      if (parent.tagName === 'DETAILS') parent.open = true;
      parent = parent.parentElement;
    }
    target.scrollIntoView({behavior: reducedMotion ? 'instant' : 'smooth', block: 'center'});
  }
  window.addEventListener('hashchange', revealReference);
  revealReference();
  if (!form) return;

  const button = form.querySelector('button');
  const cursor = form.elements.cursor;
  const error = document.getElementById('review-error');
  const label = document.getElementById('review-progress');
  const steps = document.getElementById('review-steps');
  const typing = document.getElementById('typing-message');
  const welcome = document.getElementById('chat-welcome');
  const phase = form.dataset.phase;
  const text = form.dataset;
  const end = Number(form.dataset.end);
  let running = false;
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const messageGap = phase === 'discussion' ? 3000 : 200;  // PolicyLens posts its issues in one call, so 3 seconds keeps them readable one by one.

  function nearBottom() {
    return scroll && scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 130;
  }
  function scrollToLatest(follow) {
    if (scroll && follow) scroll.scrollTo({top: scroll.scrollHeight, behavior: reducedMotion ? 'instant' : 'smooth'});
  }
  function showTyping(state) {
    const follow = nearBottom();
    if (welcome) welcome.hidden = true;
    typing.hidden = false;
    typing.classList.toggle('is-self', state.next_is_self);
    const name = typing.querySelector('[data-typing-name]');
    if (name) {
      name.textContent = state.next_name;
      typing.querySelector('[data-typing-avatar]').textContent = state.next_name.slice(0, 1);
    }
    label.textContent = text.typing.replace('{name}', state.next_name);
    scrollToLatest(follow);
  }
  async function display(state, animate) {
    cursor.value = String(state.cursor);
    error.textContent = state.error;
    const template = document.createElement('template');
    template.innerHTML = state.steps_html;
    let shown = false;
    for (const message of template.content.querySelectorAll('[data-phase]')) {
      if (message.dataset.phase !== phase || document.getElementById(message.id)) continue;
      if (shown && animate && !reducedMotion) await delay(messageGap);
      shown = true;
      const follow = nearBottom();
      if (animate) message.classList.add('message-enter');
      steps.append(message);
      if (welcome) welcome.hidden = true;
      scrollToLatest(follow);
    }
    const issues = document.getElementById('issue-cards');
    if (issues && state.issues_html) issues.innerHTML = state.issues_html;
  }
  async function request(url, options = {}, animate = false) {
    const response = await fetch(url, {
      ...options, credentials: 'same-origin',
      headers: {Accept: 'application/json'}, cache: 'no-store'
    });
    if (!response.headers.get('content-type')?.includes('application/json')) {
      throw new Error(text.unreachable);
    }
    const state = await response.json();
    if (animate && !reducedMotion) await delay(350);
    typing.hidden = true;
    await display(state, animate);
    if (!response.ok) throw new Error(state.message || state.error || text.paused);
    return state;
  }
  async function start(event) {
    if (event) event.preventDefault();
    if (running) return;
    running = true;
    button.disabled = true;
    button.hidden = true;
    error.textContent = '';
    try {
      let state = await request(form.dataset.statusUrl);
      while (state.cursor < end) {
        showTyping(state);
        state = await request(form.action, {method: 'POST', body: new FormData(form)}, true);
      }
      label.textContent = text.done;
      form.hidden = true;
      document.getElementById('phase-next').hidden = false;
      if (phase === 'proposal') window.location.reload();
    } catch (problem) {
      error.textContent = problem instanceof TypeError
        ? text.offline
        : problem.message;
      label.textContent = text.saved;
    } finally {
      typing.hidden = true;
      running = false;
      button.disabled = false;
      button.hidden = false;
      button.textContent = text.retry;
    }
  }
  form.addEventListener('submit', start);
  const url = new URL(window.location.href);
  const autoStart = url.searchParams.get('start') === '1';
  url.searchParams.delete('start');
  url.searchParams.set('page', phase);
  window.history.replaceState(null, '', url);
  if (autoStart) start();
})();
