(() => {
  const cfg = window.purrChildAdmin;
  if (!cfg) return;
  let data = cfg.initial;
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const status = (row, version, verified = true) => {
    if (!verified) return '<span style="color:#996800">Unable to verify (last known status)</span>';
    if (row.status === 'update_available') {
      return '<span style="color:#996800">Newer version available: ' +
        escapeHtml(version == null ? 'unversioned' : version) + '</span>';
    }
    if (row.status === 'removed_upstream') return '<span style="color:#996800">Removed upstream</span>';
    return '<span style="color:#18733b">Up to date</span>';
  };
  const buttons = (check, update) =>
    '<p><button class="button" data-operation="' + check + '">Check Versions</button> ' +
    '<button class="button button-primary" data-operation="' + update + '">Update All</button></p>';
  const checked = snapshot => snapshot?.checked_at
    ? new Date(snapshot.checked_at * 1000).toLocaleString() : 'Never checked';
  const empty = '<p>No verified status yet. Click Check Versions.</p>';
  const registry = document.getElementById('purr-admin-registry');
  const knowledge = document.getElementById('purr-admin-knowledge');
  const settings = document.getElementById('purr-admin-settings');
  function draw() {
    const r = data.registry || {};
    const registryVerified = !!r.checked_at && (data.heartbeat?.registry_versions?.failures ?? 0) === 0;
    registry.innerHTML = '<h2>Product Registry</h2>' +
      buttons('check_registry','update_registry') +
      '<p>Last checked: ' + escapeHtml(checked(r)) + '</p>' +
      (!r.rows ? empty : '<table class="widefat striped"><thead><tr><th>Product</th><th>Installed</th><th>Status</th></tr></thead><tbody>' +
      r.rows.map(row => '<tr><td>' + escapeHtml(row.product_id) + '</td><td>' +
      escapeHtml(row.installed) + '</td><td>' + status(row,row.latest,registryVerified) + '</td></tr>').join('') +
      '</tbody></table>');
    const k = data.knowledge || {};
    const knowledgeVerified = !!k.checked_at && (data.heartbeat?.knowledge_versions?.failures ?? 0) === 0;
    const products = {};
    for (const item of k.rows || []) {
      (products[item.product_id] ||= []).push(item);
    }
    let tree = '';
    for (const [product, items] of Object.entries(products)) {
      const groups = {};
      for (const item of items) {
        const path = item.source.includes('://') ? item.source.split('://')[1] : item.source;
        const segments = path.split('/');
        const category = segments.slice(0,-1).join(' / ') || 'General';
        (groups[category] ||= []).push(item);
      }
      tree += '<details open><summary><strong>' + escapeHtml(product) + '</strong></summary><div style="margin:12px 0 14px 24px">';
      for (const [category, entries] of Object.entries(groups)) {
        tree += '<details open><summary>' + escapeHtml(category) + '</summary><table class="widefat striped" style="margin:8px 0 14px 18px;max-width:920px"><thead><tr><th>Knowledge</th><th>Local revision</th><th>Status</th></tr></thead><tbody>';
        for (const item of entries) {
          tree += '<tr><td>' + escapeHtml(item.id) + '</td><td>' +
            escapeHtml(item.revision == null ? 'Legacy' : 'r'+item.revision) + '</td><td>' +
            status(item,item.latest_revision == null ? null : 'r'+item.latest_revision,knowledgeVerified) + '</td></tr>';
        }
        tree += '</tbody></table></details>';
      }
      tree += '</div></details>';
    }
    knowledge.innerHTML = '<h2>Knowledge Library</h2>' +
      buttons('check_knowledge','sync_knowledge') +
      '<p>Last checked: ' + escapeHtml(checked(k)) + '</p>' +
      (k.rows ? (tree || '<p>No approved shared knowledge available.</p>') : empty);
    const hb = data.heartbeat || {};
    let heartbeats = '<table class="widefat striped"><thead><tr><th>Component</th><th>Last success</th><th>Failures</th></tr></thead><tbody>';
    for (const [id,value] of Object.entries(hb)) {
      heartbeats += '<tr><td>' + escapeHtml(id) + '</td><td>' +
        escapeHtml(checked({checked_at:value.last_success})) + '</td><td>' +
        escapeHtml(value.failures ?? 0) + '</td></tr>';
    }
    heartbeats += '</tbody></table>';
    const health = data.network || {};
    let serviceRows = '<table class="widefat striped"><thead><tr><th>Component</th><th>Status</th><th>Detail</th></tr></thead><tbody>';
    for (const id of ['child','purra','sophira']) {
      const service = health[id] || {};
      const state = service.status || 'not_checked';
      const label = state === 'healthy' ? 'Healthy' :
        state === 'degraded' ? 'Degraded' :
        state === 'unavailable' ? 'Unavailable' : 'Not checked';
      const tone = state === 'healthy' ? '#18733b' : '#996800';
      serviceRows += '<tr><td><strong>' + escapeHtml(id === 'child' ? 'Purr Child' : id === 'purra' ? 'Purra' : 'Sophira') +
        '</strong></td><td><span style="color:' + tone + '">' + label + '</span></td><td>' +
        escapeHtml(service.detail || 'Run Health Check') + '</td></tr>';
    }
    serviceRows += '</tbody></table>';
    settings.innerHTML = '<h2>Purr Child Settings & Diagnostics</h2><p><strong>Current version:</strong> ' +
      escapeHtml(data.plugin_version) + '</p><h3>AI Network Health</h3>' +
      '<p><button class="button" data-operation="health_check">Run Health Check</button> ' +
      '<button class="button" id="purr-copy-diagnostics">Copy Diagnostic Report</button></p>' +
      '<p>Last checked: ' + escapeHtml(checked(health)) + '</p>' +
      serviceRows + '<h3>Heartbeat history</h3>' + heartbeats +
      '<h3>Integrity & Recovery</h3>' +
      '<p>Trusted release checksum: Not available. Integrity is not claimed.</p>' +
      '<p>Rollback: Deferred until verified releases and safe restore support are available.</p>';
  }
  async function operate(op, button) {
    const old = button.textContent;
    button.disabled = true;
    button.textContent = 'Working…';
    const body = new URLSearchParams({action:'purr_child_admin_action',nonce:cfg.nonce,operation:op});
    try {
      const response = await fetch(cfg.endpoint,{method:'POST',credentials:'same-origin',body});
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.data?.message || result.data || 'Request failed');
      data = result.data;
      draw();
    } catch (error) {
      window.alert('Purr Child: ' + error.message);
    } finally {
      button.disabled = false;
      button.textContent = old;
    }
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-operation]');
    if (button) operate(button.dataset.operation,button);
    if (event.target.closest('#purr-copy-diagnostics')) {
      const report = JSON.stringify({
        plugin_version:data.plugin_version,network:data.network,heartbeat:data.heartbeat,
        registry:data.registry,knowledge:data.knowledge
      },null,2);
      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(report).catch(() => window.prompt('Copy report:',report));
      } else window.prompt('Copy report:',report);
    }
  });
  for (const link of document.querySelectorAll('[data-purr-tab]')) {
    link.addEventListener('click', event => {
      event.preventDefault();
      const current = link.dataset.purrTab;
      for (const tab of document.querySelectorAll('[data-purr-tab]'))
        tab.classList.toggle('nav-tab-active',tab.dataset.purrTab === current);
      for (const panel of document.querySelectorAll('.purr-admin-panel'))
        panel.hidden = panel.id !== 'purr-admin-' + current;
    });
  }
  draw();
})();
