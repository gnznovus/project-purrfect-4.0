(() => {
  'use strict';
  const cfg = window.purrChildAdmin;
  if (!cfg) return;
  let data = cfg.initial || {};
  let busy = false;
  let polling = false;
  const knowledgeAvailable = () => data.network?.purra?.status === 'healthy' && data.network?.sophira?.status === 'healthy';
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date = v => v ? new Date(v * 1000).toLocaleString() : 'Not checked';
  const productLabel = id => String(id).split(/[-_]+/).filter(Boolean).map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
  const knowledgeSource = item => {
    const source = String(item.source || '');
    const revision = item.revision;
    const version = String(item.product_version || '');
    if (!Number.isInteger(revision) || revision < 1 || !version || !source.includes('://')) return source;
    const index = source.indexOf('://');
    return source.slice(0,index) + '-' + version + source.slice(index) + '-r' + revision;
  };
  const badge = (state, version, verified = true, knowledge = false) => {
    if (!verified) return '<span class="purr-status is-unknown">Unable to verify</span>';
    if (state === 'update_available') return '<span class="purr-status is-warn">Newer version available: ' + esc(version == null ? 'unknown' : (knowledge ? 'Revision ' + version : version)) + '</span>';
    if (state === 'removed_upstream') return '<span class="purr-status is-warn">Removed upstream</span>';
    if (state === 'healthy') return '<span class="purr-status">Healthy</span>';
    if (state === 'degraded') return '<span class="purr-status is-warn">Degraded</span>';
    if (state === 'unavailable') return '<span class="purr-status is-error">Unavailable</span>';
    if (state !== 'up_to_date') return '<span class="purr-status is-unknown">Not checked</span>';
    return '<span class="purr-status">Up to date</span>';
  };
  const controls = (check, update, disabled = false) => '<div class="purr-actions">' +
    '<button type="button" class="purr-action" data-operation="' + check + '" ' + (disabled ? 'disabled title="Sophia is unavailable"' : '') + '><span class="purr-action-icon" aria-hidden="true">↻</span>Check Versions</button>' +
    '<button type="button" class="purr-action is-primary" data-operation="' + update + '" ' + (disabled ? 'disabled title="Sophia is unavailable"' : '') + '><span class="purr-action-icon" aria-hidden="true">↓</span>Update All</button></div>';
  const head = (title, description, actions) => '<div class="purr-panel-head"><div><h2>' +
    title + '</h2><p>' + description + '</p></div>' + (actions || '') + '</div>';
  const table = (columns, content) => '<div class="purr-table-wrap"><table class="purr-data-table"><thead><tr>' +
    columns.map(x => '<th scope="col">' + x + '</th>').join('') + '</tr></thead><tbody>' + content + '</tbody></table></div>';
  const card = (title, content, subtitle = '') => '<div class="purr-card"><div class="purr-card-heading"><span>' +
    title + '</span><small>' + subtitle + '</small></div>' + content + '</div>';
  const els = {
    registry: document.getElementById('purr-admin-registry'),
    knowledge: document.getElementById('purr-admin-knowledge'),
    settings: document.getElementById('purr-admin-settings')
  };
  const feedback = document.getElementById('purr-admin-feedback');
  function draw() {
    const registry = data.registry || {}, knowledge = data.knowledge || {};
    const rv = !!registry.checked_at && (data.heartbeat?.registry_versions?.failures ?? 0) === 0;
    const kv = !!knowledge.checked_at && (data.heartbeat?.knowledge_versions?.failures ?? 0) === 0;
    const regRows = Array.isArray(registry.rows) ? registry.rows : [];
    const regTable = regRows.length ? table(['Product', 'Installed', 'Version status'], regRows.map(row =>
      '<tr><td><div class="purr-item-name">' + esc(productLabel(row.product_id)) + '</div></td><td class="purr-monovalue">' +
      esc(row.installed) + '</td><td>' + badge(row.status, row.latest, rv) + '</td></tr>').join('')) :
      '<div class="purr-empty">No verified registry versions yet. Run Check Versions to inspect active products.</div>';
    els.registry.innerHTML = head('Product Registry',
      'Active Purrfect products · WordPress-native version checks and updates',
      controls('check_registry', 'update_registry')) +
      '<p class="purr-checkline">Last version check: ' + esc(date(registry.checked_at)) + '</p>' +
      card('Registered products', regTable, regRows.length + ' active signals');
    const available = knowledgeAvailable();
    const items = Array.isArray(knowledge.rows) ? knowledge.rows : [];
    const products = new Map();
    for (const item of items) {
      if (!products.has(item.product_id)) products.set(item.product_id, new Map());
      const rawPath = String(item.source || '');
      const path = rawPath.includes('://') ? rawPath.split('://').slice(1).join('://') : rawPath;
      const parts = path.split('/');
      const group = parts.slice(0, -1).join(' / ') || 'General';
      const categories = products.get(item.product_id);
      if (!categories.has(group)) categories.set(group, []);
      categories.get(group).push(item);
    }
    let tree = '';
    for (const [name,categories] of products) {
      tree += '<details open><summary>' + esc(name) + '</summary><div class="purr-tree-categories">';
      for (const [category,entries] of categories) {
        tree += '<details class="purr-category" open><summary>' + esc(category) + '</summary>' +
          table(['Knowledge entry','Local revision','Version status'], entries.map(item =>
          '<tr><td><div class="purr-item-name">' + esc(item.id) + '</div><div class="purr-item-sub">' +
          esc(knowledgeSource(item)) + '</div></td><td class="purr-knowledge-rev">' +
          esc(item.revision != null ? 'Revision ' + item.revision : (item.origin === 'built_in' ? productLabel(name) + ' Built-in' : item.origin === 'not_synchronized' ? 'Not synchronized' : 'Unversioned lease')) + '</td><td>' +
          (available ? badge(item.status,item.latest_revision,kv,true) : '<span class="purr-status is-unknown">Last verified status</span>') +
          '</td></tr>').join('')) + '</details>';
      }
      tree += '</div></details>';
    }
    els.knowledge.innerHTML = head('Knowledge Library',
      'Approved Sophia entries · independent revisions and read-only version checks',
      controls('check_knowledge', 'sync_knowledge', !available)) +
      (!available ? '<p class="purr-dependency-note">Sophia is unavailable or not yet verified. Knowledge version checks and updates are paused; local knowledge remains accessible. Controls resume automatically on recovery.</p>' : '') +
      '<p class="purr-checkline">Last version check: ' + esc(date(knowledge.checked_at)) + '</p>' +
      card('Knowledge explorer', '<div class="purr-tree">' + (tree ||
      '<div class="purr-empty">No verified knowledge versions yet. Use Check Versions to inspect the library.</div>') +
      '</div>', items.length + ' entries');
    const network = data.network || {};
    const nodes = [['child','Purr Assistant'],['purra','Purr'],['sophira','Sophia']];
    const healthCards = nodes.map(([key,label]) => {
      const node = network[key] || {};
      const mark = key === 'child' || key === 'purra' ? '<img class="purr-health-mark" src="' + esc(cfg.purrIcon) + '" alt="" />' : '';
      return '<div class="purr-health-node"><div class="purr-health-name">' + mark + esc(label) + '</div>' +
        badge(node.status) + '<p>' + esc(node.detail || 'Run Health Check to inspect this component.') + '</p></div>';
    }).join('');
    const heartbeats = data.heartbeat || {};
    const hbRows = Object.entries(heartbeats).map(([key,value]) =>
      '<tr><td class="purr-item-name">' + esc(key.replaceAll('_',' ')) + '</td><td>' +
      esc(date(value.last_success)) + '</td><td class="purr-monovalue">' +
      esc(value.failures ?? 0) + '</td></tr>').join('');
    els.settings.innerHTML = head('Settings & Diagnostics',
      'Local plugin information and independent AI network health checks',
      '<div class="purr-actions"><button type="button" class="purr-action is-primary" data-operation="health_check">Run Health Check</button>' +
      '<button type="button" class="purr-action" id="purr-copy-diagnostics">Copy Diagnostics</button></div>') +
      '<div class="purr-stat-grid"><div class="purr-stat"><div class="purr-stat-label">Purr Assistant version</div>' +
      '<div class="purr-stat-value">' + esc(data.plugin_version || 'Unknown') + '</div></div>' +
      '<div class="purr-stat"><div class="purr-stat-label">Last network check</div>' +
      '<div class="purr-stat-value" style="font-size:16px">' + esc(date(network.checked_at)) + '</div></div></div>' +
      '<h3 class="purr-section-title">AI Network Health</h3><div class="purr-health-grid">' + healthCards + '</div>' +
      '<h3 class="purr-section-title">Heartbeat history</h3>' +
      card('Scheduled components', hbRows ? table(['Component','Last success','Failures'],hbRows) :
      '<div class="purr-empty">No heartbeat history available.</div>') +
      '<h3 class="purr-section-title">Integrity & Recovery</h3>' +
      card('Plugin diagnostics','<div style="padding:18px 20px"><div class="purr-stat-label">Bootstrap SHA-256 · diagnostic only</div>' +
      '<div class="purr-digest">' + esc(data.bootstrap_checksum || 'Unavailable') + '</div>' +
      '<p class="purr-footnote">This is not a verified release checksum. Trusted release integrity and safe rollback remain deferred until release manifests and restore support are available.</p></div>');
  }
  async function operate(operation, button) {
    if (busy) return;
    if ((operation === 'check_knowledge' || operation === 'sync_knowledge') && !knowledgeAvailable()) return;
    busy = true;
    button.disabled = true;
    const label = button.innerHTML;
    button.textContent = 'Working…';
    feedback.textContent = '';
    feedback.classList.remove('is-error');
    try {
      const body = new URLSearchParams({ action:'purr_child_admin_action', nonce:cfg.nonce, operation });
      const response = await fetch(cfg.endpoint,{ method:'POST', credentials:'same-origin', body });
      const result = await response.json();
      if (!response.ok || !result.success) {
        if (result.data?.reason === 'dependency_unavailable') {
          data = result.data.data;
          draw();
          feedback.textContent = 'Sophia is unavailable. Knowledge actions are paused.';
          return;
        }
        throw new Error(result.data?.message || (typeof result.data === 'string' ? result.data : 'Request failed'));
      }
      data = result.data;
      draw();
      feedback.textContent = operation === 'health_check' ? 'Network health checked.' :
        operation.startsWith('check_') ? 'Version check completed.' : 'Update operation completed.';
    } catch (error) {
      feedback.classList.add('is-error');
      feedback.textContent = 'Operation failed: ' + error.message;
    } finally {
      busy = false;
      if (button.isConnected) { button.disabled = false; button.innerHTML = label; }
    }
  }
  async function refreshStatus() {
    if (polling || busy || document.hidden) return;
    polling = true;
    try {
      const body = new URLSearchParams({action:'purr_child_admin_status',nonce:cfg.nonce});
      const response = await fetch(cfg.endpoint,{method:'POST',credentials:'same-origin',body});
      const result = await response.json();
      if (response.ok && result.success) {
        const previous = knowledgeAvailable();
        data = result.data;
        if (previous !== knowledgeAvailable()) {
          draw();
          feedback.classList.remove('is-error');
          feedback.textContent = knowledgeAvailable()
            ? 'Sophia has recovered. Knowledge controls are available.'
            : 'Sophia is unavailable. Knowledge controls are paused.';
        } else if (document.querySelector('[data-purr-tab="settings"].is-active')) draw();
      }
    } catch (_) {
      // A polling failure cannot invalidate the last-good lease or enable controls.
      data.network = {...data.network, sophira:{status:'unavailable'},purra:{status:'unavailable'}};
      draw();
    } finally { polling = false; }
  }
  setInterval(refreshStatus, 15000);
  refreshStatus();
  document.addEventListener('click', event => {
    const btn = event.target.closest('[data-operation]');
    if (btn) return void operate(btn.dataset.operation,btn);
    if (event.target.closest('#purr-copy-diagnostics')) {
      const report = JSON.stringify({
        plugin_version:data.plugin_version,bootstrap_checksum:data.bootstrap_checksum,
        network:data.network,heartbeat:data.heartbeat,
        registry:data.registry,knowledge:data.knowledge
      },null,2);
      if (navigator.clipboard?.writeText) navigator.clipboard.writeText(report).then(() => {
        feedback.textContent = 'Diagnostic report copied.';
      }).catch(() => window.prompt('Copy report:',report));
      else window.prompt('Copy report:',report);
    }
    const tab = event.target.closest('[data-purr-tab]');
    if (tab) {
      const selected = tab.dataset.purrTab;
      for (const entry of document.querySelectorAll('[data-purr-tab]')) {
        const active = entry.dataset.purrTab === selected;
        entry.classList.toggle('is-active',active);
        entry.setAttribute('aria-selected',String(active));
      }
      for (const [name,panel] of Object.entries(els)) panel.hidden = name !== selected;
    }
  });
  // Mascot timers run independently of the AJAX-rendered panels.
  const mascot = document.querySelector('.purr-header-mark');
  if (mascot) {
    const open = mascot.querySelector('.purr-head-open');
    const closed = mascot.querySelector('.purr-head-closed');
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let timer = null;
    let held = false;
    const showClosed = value => mascot.classList.toggle('is-eyes-closed', value);
    const cancel = () => { if (timer !== null) clearTimeout(timer); timer = null; };
    const schedule = () => {
      cancel();
      if (held || document.hidden || reduced.matches) return;
      timer = setTimeout(() => {
        if (held || document.hidden || reduced.matches) return;
        showClosed(true);
        timer = setTimeout(() => { showClosed(false); schedule(); }, 500);
      }, 6000 + Math.random() * 6000);
    };
    const hold = () => { held = true; cancel(); showClosed(true); };
    const release = () => { held = false; showClosed(false); schedule(); };
    mascot.addEventListener('pointerenter', hold);
    mascot.addEventListener('pointerleave', release);
    mascot.addEventListener('focus', hold);
    mascot.addEventListener('blur', release);
    document.addEventListener('visibilitychange', () => {
      cancel(); showClosed(held); if (!document.hidden) schedule();
    });
    if (reduced.addEventListener) reduced.addEventListener('change', () => {
      showClosed(held); schedule();
    });
    // Start the clock independently of image decoding: an offscreen/hidden
    // frame may never resolve decode() in some browsers despite being usable.
    // Hover switching already proves both frames can be displayed.
    if (open && closed) {
      schedule();
      Promise.all([open, closed].map(img => img.decode().catch(() => {}))).then(() => {
        if (!open.naturalWidth || !closed.naturalWidth) {
          cancel();
          mascot.classList.add('has-unavailable-frames');
        }
      });
    }
  }
  draw();
})();
