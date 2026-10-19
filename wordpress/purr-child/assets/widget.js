(() => {
  'use strict';
  const cfg = window.purrChildWidget;
  const root = document.getElementById('purr-child-widget');
  if (!cfg || !root) return;
  const storageKey = 'purr-child:v1:' + location.origin + ':' + cfg.scope;
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}'); } catch { saved = {}; }
  if (!saved || typeof saved !== 'object' || Array.isArray(saved)) saved = {};
  let session = typeof saved.session === 'string' && /^[\w-]{8,128}$/.test(saved.session)
    ? saved.session : (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + '-session');
  const history = Array.isArray(saved.history) ? saved.history.slice(-60).filter(
    x => x && ['You','Purr','Purra','Source','Connection'].includes(x.role) && typeof x.text === 'string' && x.text.length < 4000) : [];
  let context = saved.context && typeof saved.context === 'object' && !Array.isArray(saved.context) ? saved.context : {};
  let pending = saved.pending && typeof saved.pending === 'object' ? saved.pending : null;
  let opened = Boolean(saved.opened);
  let greeted = Boolean(saved.greeted);
  let busy = false;
  let debugMode = Boolean(saved.debugMode);
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  };
  const avatar = () => {
    const img = element('img', 'pc-avatar');
    img.src = cfg.purraAvatar; img.alt = ''; img.loading = 'eager';
    return img;
  };
  const fab = element('button', 'pc-fab');
  fab.append(avatar());
  fab.type = 'button'; fab.setAttribute('aria-label', 'Open Purr Assistant');
  const greeting = element('div', 'pc-greeting', "Hi! I'm here if you need help.");
  const panel = element('section', 'pc-panel');
  panel.setAttribute('aria-label', 'Purr Assistant chat');
  const head = element('div', 'pc-head');
  const title = element('span', 'pc-title');
  title.append(avatar(), element('span', '', 'Purr Assistant'));
  head.append(title);
  const controls = element('div', 'pc-head-actions');
  const newChat = element('button', 'pc-new-chat', '✎');
  newChat.type = 'button'; newChat.title = 'New Chat';
  newChat.setAttribute('aria-label', 'New Chat');
  controls.append(newChat);
  const close = element('button', 'pc-close', '×');
  close.type = 'button'; close.setAttribute('aria-label', 'Collapse Purr Assistant');
  controls.append(close);
  head.append(controls);
  const log = element('div', 'pc-log');
  log.setAttribute('role', 'log');
  const status = element('div', 'pc-status');
  status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  status.hidden = true;
  const form = element('form', 'pc-form');
  const input = element('input');
  input.type = 'text'; input.maxLength = 2000; input.required = true;
  input.placeholder = 'Ask Purr...'; input.setAttribute('aria-label', 'Message');
  const send = element('button', '', 'Send'); send.type = 'submit';
  form.append(input, send);
  panel.append(head, log, status, form);
  root.append(greeting, fab, panel);
  function save() {
    try { sessionStorage.setItem(storageKey, JSON.stringify({
      session, history: history.slice(-60), context, pending, opened, greeted, debugMode
    })); } catch { /* Storage may be unavailable; chat still works. */ }
  }
  function redraw() {
    panel.hidden = !opened; fab.hidden = opened; greeting.hidden = opened || greeted;
  }
  function renderMessage(entry) {
    const line = element('div', 'pc-line' + (entry.role === 'You' ? ' pc-line-user' : ''));
    if (entry.role === 'Purr' || entry.role === 'Purra') line.append(avatar());
    const bubble = element('div', 'pc-bubble');
    bubble.append(element('p', 'pc-item' + (entry.role === 'You' ? ' pc-user' : ''), entry.text));
    if (entry.options && Array.isArray(entry.options) && !entry.consumed
        && pending && pending.turn === entry.turn) {
      const choices = element('div', 'pc-actions');
      for (const option of entry.options) {
        if (typeof option.id !== 'string' || typeof option.label !== 'string') continue;
        const button = element('button', '', option.label);
        button.type = 'button';
        button.disabled = !pending || pending.turn !== entry.turn || busy;
        button.addEventListener('click', () => {
          if (busy || !pending || pending.turn !== entry.turn) return;
          remember('You', option.label);
          submit('', option.id);
        });
        choices.append(button);
      }
      bubble.append(choices);
    }
    if (entry.trace && typeof entry.trace === 'object' && Array.isArray(entry.trace.stages)) {
      const details = element('details', 'pc-debug');
      const summary = element('summary', '', 'Debug trace · ' + (entry.trace.duration_ms ?? '?') + ' ms');
      details.append(summary);
      const list = element('ol', '');
      for (const stage of entry.trace.stages) {
        if (!stage || typeof stage !== 'object') continue;
        const bits = [stage.stage, stage.result, stage.ms == null ? '' : stage.ms + ' ms',
          stage.status ? 'status: ' + stage.status : '',
          stage.buttons == null ? '' : stage.buttons + ' buttons',
          stage.sources == null ? '' : stage.sources + ' sources',
          stage.load_ms == null ? '' : 'model load: ' + stage.load_ms + ' ms',
          stage.prompt_eval_ms == null ? '' : 'prompt: ' + stage.prompt_eval_ms + ' ms',
          stage.eval_ms == null ? '' : 'generation: ' + stage.eval_ms + ' ms',
          stage.prompt_eval_count == null ? '' : 'input: ' + stage.prompt_eval_count + ' tokens',
          stage.eval_count == null ? '' : 'output: ' + stage.eval_count + ' tokens'].filter(Boolean);
        list.append(element('li', '', bits.join(' · ')));
      }
      details.append(list);
      bubble.append(details);
    }
    line.append(bubble);
    log.append(line);
    log.scrollTop = log.scrollHeight;
  }
  function remember(role, text, options = null, trace = null) {
    const entry = { role, text };
    if (trace) entry.trace = trace;
    if (options) {
      entry.turn = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
      entry.options = options;
      pending = { turn: entry.turn };
    }
    history.push(entry);
    if (history.length > 60) history.shift();
    renderAll();
    save();
  }
  function renderAll() {
    log.replaceChildren();
    for (const entry of history) renderMessage(entry);
  }
  if (!history.length) history.push({ role: 'Purr', text: "Hi! I'm here if you need help." });
  // Legacy pending data belonged to the fixed bottom action strip. Never
  // resurrect choices without an associated Purra response.
  if (!history.some(item => item.turn && pending && item.turn === pending.turn)) pending = null;
  for (const entry of history) if (entry.role === 'Purra') entry.role = 'Purr';
  renderAll();
  redraw();
  fab.addEventListener('click', () => { opened = true; greeted = true; redraw(); save(); input.focus(); });
  close.addEventListener('click', () => { opened = false; redraw(); save(); });
  newChat.addEventListener('click', () => {
    if (busy) return;
    session = crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + '-new-chat';
    history.length = 0;
    context = {};
    pending = null;
    history.push({ role: 'Purr', text: "Hi! I'm here if you need help." });
    input.value = '';
    renderAll();
    save();
    input.focus();
  });
  async function submit(message, selection = null) {
    if (busy) return;
    busy = true; send.disabled = true;
    const previousPending = pending;
    pending = null;
    // Any new turn supersedes previous suggestions. Hide them, don't leave
    // a trail of disabled buttons in conversation history.
    if (previousPending) {
      const previousEntry = history.find(entry => entry.turn === previousPending.turn);
      if (previousEntry) { previousEntry.consumed = true; delete previousEntry.options; }
    }
    renderAll(); save();
    const started = performance.now();
    const update = () => {
      const seconds = Math.floor((performance.now() - started) / 1000);
      const stage = seconds < 3 ? 'Request sent to Purr.' :
        seconds < 7 ? 'Waiting for the Brain...' : 'Still waiting for a response...';
      status.textContent = 'Thinking... ' + seconds + 's\n[verbose] ' + stage;
      status.hidden = false;
    };
    update();
    const tick = setInterval(update, 1000);
    try {
      const body = new FormData();
      body.set('action', 'purr_child_chat'); body.set('nonce', cfg.nonce);
      body.set('session', session); body.set('message', message);
      body.set('context', JSON.stringify(context));
      if (debugMode) body.set('debug', '1');
      if (selection !== null) body.set('selection', selection);
      const res = await fetch(cfg.endpoint, { method: 'POST', body });
      const result = await res.json();
      if (!res.ok || !result.success) throw new Error(
        typeof result.data === 'string' ? result.data : 'Request failed');
      const data = result.data;
      const choices = data.interaction && Array.isArray(data.interaction.options)
        ? data.interaction.options : null;
      remember('Purr', data.message || 'No response.', choices, debugMode ? data.debug : null);
      if (Array.isArray(data.sources) && data.sources.length) {
        remember('Source', data.sources.map(x => x.source).filter(Boolean).join(', '));
      }
      if (data.context && typeof data.context === 'object' && !Array.isArray(data.context)) context = data.context;
      // The accepted answer supersedes the previous interaction. Keep its
      // question bubble, but remove the used buttons from that old message.
      if (selection !== null && previousPending) {
        const earlier = history.find(entry => entry.turn === previousPending.turn);
        if (earlier) { earlier.consumed = true; delete earlier.options; }
      }
      renderAll(); save();
    } catch (error) {
      remember('Connection', error.message);
      // A failed selection can be retried; restore its buttons as well.
      if (selection !== null && previousPending) {
        pending = previousPending;
        const previousEntry = history.find(entry => entry.turn === previousPending.turn);
        if (previousEntry) previousEntry.consumed = false;
      }
      renderAll(); save();
    }
    finally { clearInterval(tick); status.hidden = true; status.textContent = '';
      busy = false; send.disabled = false;
      // Render enabled choices after the request has settled.
      renderAll();
    }
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    input.value = '';
    if (text === '--debug') {
      debugMode = !debugMode;
      remember('You', text);
      remember('Purr', debugMode
        ? 'Debug mode ON. Each new response will include an expandable diagnostic trace.'
        : 'Debug mode OFF. Diagnostic traces are hidden for new responses.');
      save();
      return;
    }
    remember('You', text); submit(text);
  });
})();