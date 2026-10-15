(() => {
  'use strict';
  const root = window.purrChildLab;
  const log = document.querySelector('#purr-log');
  const options = document.querySelector('#purr-options');
  const input = document.querySelector('#purr-question');
  const send = document.querySelector('#purr-send');
  if (!root || !log || !options || !input || !send) return;
  const session = globalThis.crypto?.randomUUID?.() || String(Date.now());
  let busy = false;
  const append = (speaker, value) => {
    const p = document.createElement('p');
    const strong = document.createElement('strong');
    strong.textContent = speaker + ': ';
    p.append(strong, document.createTextNode(value));
    log.append(p);
    log.scrollTop = log.scrollHeight;
  };
  async function submit(message, selection = null) {
    if (busy) return;
    busy = true;
    send.disabled = true;
    options.replaceChildren();
    if (selection === null) append('You', message);
    try {
      const form = new FormData();
      form.set('action', 'purr_child_chat');
      form.set('nonce', root.nonce);
      form.set('session', session);
      form.set('message', message);
      if (selection !== null) form.set('selection', selection);
      const response = await fetch(root.endpoint, { method: 'POST', body: form });
      const packet = await response.json();
      if (!response.ok || !packet.success) throw new Error(
        typeof packet.data === 'string' ? packet.data : 'Request failed');
      const data = packet.data;
      append('Purra', data.message);
      if (data.routing) append('Routing', data.routing);
      if (data.interaction?.options?.length) {
        for (const option of data.interaction.options) {
          const button = document.createElement('button');
          button.className = 'button';
          button.style.margin = '4px';
          button.textContent = option.label;
          button.addEventListener('click', () => {
            append('You', option.label);
            submit('', option.id);
          });
          options.append(button);
        }
      }
      if (data.sources?.length) append('Sources', data.sources.map(s => s.source).join(', '));
    } catch (error) {
      append('Connection', error.message);
    } finally {
      busy = false;
      send.disabled = false;
    }
  }
  send.addEventListener('click', () => {
    if (!input.value.trim()) return;
    const text = input.value.trim();
    input.value = '';
    submit(text);
  });
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); send.click(); }
  });
})();
