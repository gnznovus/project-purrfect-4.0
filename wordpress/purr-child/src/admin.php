<?php
/** Purr Child administration: reuse heartbeat for version checks and verified sync. */
defined('ABSPATH') || exit;

function purr_child_registry_version_rows(bool $refresh = false): array {
    if (!function_exists('get_plugins')) {
        require_once ABSPATH . 'wp-admin/includes/plugin.php';
    }
    if ($refresh) {
        require_once ABSPATH . 'wp-includes/update.php';
        wp_update_plugins();
        wp_update_themes();
    }
    $available_plugins = (array) (get_site_transient('update_plugins')->response ?? []);
    $available_themes = (array) (get_site_transient('update_themes')->response ?? []);
    $plugins = get_plugins();
    $themes = wp_get_themes();
    $inventory = purr_child_discover();
    $rows = [];
    foreach ($inventory['signals'] as $signal) {
        $kind = $signal['kind'];
        $key = $signal['key'];
        $installed = $kind === 'plugin'
            ? ($plugins[$key]['Version'] ?? null)
            : (isset($themes[$key]) ? $themes[$key]->get('Version') : null);
        $update = $kind === 'plugin'
            ? ($available_plugins[$key]->new_version ?? null)
            : ($available_themes[$key]['new_version'] ?? null);
        $rows[] = [
            'product_id' => $signal['product_id'], 'kind' => $kind, 'key' => $key,
            'installed' => is_string($installed) ? $installed : $signal['version'],
            'latest' => is_string($update) && $update !== '' ? $update : null,
            'status' => $update && version_compare($update, (string) $installed, '>')
                ? 'update_available' : 'up_to_date',
        ];
    }
    return $rows;
}

function purr_child_check_registry_versions(): bool {
    $rows = purr_child_registry_version_rows(true);
    update_option('purr_child_registry_version_status', [
        'checked_at' => time(), 'rows' => $rows,
    ], false);
    return true;
}

/** Read-only preview against Sophira. Never commits a fetched lease. */
function purr_child_check_knowledge_versions(): bool {
    $registry = get_option('purr_child_registry', []);
    $leases = get_option('purr_child_knowledge_leases', []);
    if (!is_array($registry) || !is_array($registry['signals'] ?? null) || !is_array($leases)) {
        return false;
    }
    $request = [];
    foreach ($registry['signals'] as $signal) {
        if (!is_string($signal['product_id'] ?? null) || !is_string($signal['version'] ?? null)) {
            continue;
        }
        $current = $leases[$signal['product_id']] ?? null;
        $valid = is_array($current) && ($current['product_version'] ?? null) === $signal['version']
            && purr_child_knowledge_valid($current);
        $request[] = [
            'id' => $signal['product_id'], 'version' => $signal['version'],
            'revision' => $valid ? $current['revision'] : null,
        ];
    }
    if (!$request) {
        update_option('purr_child_knowledge_version_status', [
            'checked_at' => time(), 'rows' => [], 'reachable' => true,
        ], false);
        return true;
    }
    $response = wp_remote_post('http://purra:8765/v1/knowledge/sync', [
        'timeout' => 20, 'headers' => ['Content-Type' => 'application/json'],
        'body' => wp_json_encode(['products' => $request]),
    ]);
    if (is_wp_error($response) || wp_remote_retrieve_response_code($response) !== 200) {
        return false;
    }
    $payload = json_decode(wp_remote_retrieve_body($response), true);
    if (!is_array($payload) || ($payload['contract_version'] ?? null) !== 1
        || !is_array($payload['updates'] ?? null)) {
        return false;
    }
    $updates = [];
    foreach ($payload['updates'] as $update) {
        if (!is_array($update) || !is_string($update['product_id'] ?? null)) {
            return false;
        }
        $updates[$update['product_id']] = $update;
    }
    $bundled = [];
    foreach ($registry['signals'] as $signal) {
        if (!is_string($signal['product_id'] ?? null) || !is_array($signal['knowledge'] ?? null)) continue;
        foreach ($signal['knowledge'] as $entry) {
            if (is_array($entry) && is_string($entry['id'] ?? null)) {
                $bundled[$signal['product_id']][$entry['id']] = true;
            }
        }
    }
    $rows = [];
    foreach ($request as $product) {
        $pid = $product['id'];
        $local = $leases[$pid] ?? null;
        $local = is_array($local) && purr_child_knowledge_valid($local) ? $local : null;
        $remote = $local;
        if (isset($updates[$pid])) {
            $base = $local ?? [
                'product_id' => $pid, 'product_version' => $product['version'],
                'revision' => 0, 'items' => [],
            ];
            $remote = purr_child_knowledge_apply($base, $updates[$pid]);
            if (!$remote) {
                return false;
            }
        }
        $local_items = [];
        foreach (($local['items'] ?? []) as $item) {
            $local_items[$item['id']] = $item;
        }
        foreach (($remote['items'] ?? []) as $item) {
            $prior = $local_items[$item['id']] ?? null;
            $newer = $prior === null || $prior !== $item;
            $rows[] = [
                'product_id' => $pid, 'product_version' => $product['version'], 'id' => $item['id'],
                'source' => $item['source'],
                'revision' => $prior['entry_revision'] ?? null,
                'origin' => $prior !== null ? 'lease' : (isset($bundled[$pid][$item['id']]) ? 'built_in' : 'not_synchronized'),
                'latest_revision' => $item['entry_revision'] ?? null,
                'status' => $newer ? 'update_available' : 'up_to_date',
            ];
            unset($local_items[$item['id']]);
        }
        foreach ($local_items as $item) {
            $rows[] = [
                'product_id' => $pid, 'product_version' => $product['version'], 'id' => $item['id'], 'source' => $item['source'],
                'revision' => $item['entry_revision'] ?? null, 'origin' => 'lease', 'latest_revision' => null,
                'status' => 'removed_upstream',
            ];
        }
    }
    update_option('purr_child_knowledge_version_status', [
        'checked_at' => time(), 'rows' => $rows, 'reachable' => true,
    ], false);
    return true;
}

/** WordPress core upgraders only; never touch unrelated installed plugins. */
function purr_child_admin_update_registry(): bool {
    if (!current_user_can('update_plugins') || !current_user_can('update_themes')) {
        return false;
    }
    $rows = purr_child_registry_version_rows(true);
    $plugins = [];
    $themes = [];
    foreach ($rows as $row) {
        if ($row['status'] !== 'update_available') continue;
        if ($row['kind'] === 'plugin') $plugins[] = $row['key'];
        if ($row['kind'] === 'theme') $themes[] = $row['key'];
    }
    if (!$plugins && !$themes) return purr_child_admin_run_check('registry_versions');
    require_once ABSPATH . 'wp-admin/includes/class-wp-upgrader.php';
    $skin = new Automatic_Upgrader_Skin();
    $success = true;
    if ($plugins) {
        $results = (new Plugin_Upgrader($skin))->bulk_upgrade($plugins);
        $success = is_array($results) && count($results) === count($plugins);
        foreach ((array) $results as $result) {
            if (is_wp_error($result) || $result === false) $success = false;
        }
    }
    if ($themes) {
        $results = (new Theme_Upgrader($skin))->bulk_upgrade($themes);
        $success = $success && is_array($results) && count($results) === count($themes);
        foreach ((array) $results as $result) {
            if (is_wp_error($result) || $result === false) $success = false;
        }
    }
    purr_child_heartbeat_dirty('registry');
    purr_child_heartbeat_dirty('knowledge');
    purr_child_heartbeat_dirty('registry_versions');
    purr_child_heartbeat_tick();
    return $success;
}

function purr_child_admin_run_check(string $component): bool {
    purr_child_heartbeat_dirty($component);
    $result = purr_child_heartbeat_tick(null, [$component]);
    return ($result[$component] ?? null) === 'success';
}

/** The three real dependencies are probed independently. Unreachable != unhealthy cache. */
function purr_child_network_health(): array {
    $leases = get_option('purr_child_knowledge_leases', []);
    $valid = is_array($leases);
    foreach ((array) $leases as $lease) {
        if (!is_array($lease) || !purr_child_knowledge_valid($lease)) $valid = false;
    }
    $result = [
        'child' => ['status' => $valid ? 'healthy' : 'degraded',
                    'detail' => $valid ? 'Local lease checksums verified' : 'Invalid local knowledge lease'],
    ];
    foreach (['purra' => '/v1/health', 'sophira' => '/v1/knowledge/health'] as $id => $path) {
        $response = wp_remote_get('http://purra:8765' . $path, ['timeout' => 5]);
        $body = is_wp_error($response) ? null : json_decode(wp_remote_retrieve_body($response), true);
        $ok = !is_wp_error($response) && wp_remote_retrieve_response_code($response) === 200
            && is_array($body) && ($body['service'] ?? null) === $id
            && ($body['status'] ?? null) === 'healthy';
        $result[$id] = [
            'status' => $ok ? 'healthy' : 'unavailable',
            'detail' => $ok ? 'Service probe passed'
                : ($id === 'sophira' ? 'Knowledge sync unavailable; last-good cache retained'
                                    : 'Chat service unavailable'),
        ];
    }
    $result['checked_at'] = time();
    update_option('purr_child_network_health', $result, false);
    return $result;
}

function purr_child_heartbeat_network_health(): bool {
    purr_child_network_health();
    return true; // Availability is data; the probe itself completed.
}

function purr_child_knowledge_dependency_ready(bool $fresh = false): bool {
    $health = get_option('purr_child_network_health', []);
    // Server-side action guard always gets a fresh probe; prevents stale enabled buttons.
    if ($fresh || !is_array($health) || !isset($health['checked_at'])
        || time() - (int) $health['checked_at'] > 75) {
        $health = purr_child_network_health();
    }
    return ($health['purra']['status'] ?? null) === 'healthy'
        && ($health['sophira']['status'] ?? null) === 'healthy';
}

function purr_child_admin_data(): array {
    $registry = get_option('purr_child_registry_version_status', []);
    $knowledge = get_option('purr_child_knowledge_version_status', []);
    $health = [];
    foreach (['registry', 'registry_versions', 'knowledge', 'knowledge_versions', 'network_health'] as $id) {
        $health[$id] = get_option('purr_child_heartbeat_' . $id, []);
    }
    return [
        'registry' => is_array($registry) ? $registry : [],
        'knowledge' => is_array($knowledge) ? $knowledge : [],
        'heartbeat' => $health,
        'network' => get_option('purr_child_network_health', []),
        'plugin_version' => get_file_data(dirname(__DIR__) . '/purr-child.php', ['Version' => 'Version'])['Version'],
        'bootstrap_checksum' => hash_file('sha256', dirname(__DIR__) . '/purr-child.php'),
    ];
}

add_action('admin_menu', static function (): void {
    add_menu_page('Purr Child Administration', 'Purr Child', 'manage_options',
        'purr-child-admin', 'purr_child_render_admin', 'data:image/svg+xml;base64,' . base64_encode('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#a7aaad" d="M4.3 10.6 3 2.3l6 3.5a10 10 0 0 1 6 0l6-3.5-1.3 8.3a8.8 8.8 0 0 1-2 8.2C16.1 20.3 14.4 21 12 21s-4.1-.7-5.7-2.2a8.8 8.8 0 0 1-2-8.2ZM8.3 13a1.4 1.4 0 1 0 0 .1Zm8.8 0a1.4 1.4 0 1 0 0 .1ZM10 16.3l2 1.7 2-1.7-2-1.1Z"/></svg>'));
});

add_action('wp_ajax_purr_child_admin_status', static function (): void {
    check_ajax_referer('purr_child_admin', 'nonce');
    if (!current_user_can('manage_options')) {
        wp_send_json_error('Permission denied', 403);
    }
    // Health recovery must also refresh the read-only version snapshot.
    // Keep lease synchronization separate: this cannot modify cached knowledge.
    $previous = get_option('purr_child_network_health', []);
    purr_child_heartbeat_tick(null, ['network_health']);
    $current = get_option('purr_child_network_health', []);
    $was_ready = is_array($previous) && ($previous['purra']['status'] ?? null) === 'healthy'
        && ($previous['sophira']['status'] ?? null) === 'healthy';
    $is_ready = is_array($current) && ($current['purra']['status'] ?? null) === 'healthy'
        && ($current['sophira']['status'] ?? null) === 'healthy';
    if ($is_ready) {
        if (!$was_ready) {
            purr_child_heartbeat_dirty('knowledge_versions');
        }
        // Retry failed checks on their existing heartbeat grid; no new scheduler.
        purr_child_heartbeat_tick(null, ['knowledge_versions']);
    }
    wp_send_json_success(purr_child_admin_data());
});

add_action('wp_ajax_purr_child_admin_action', static function (): void {
    check_ajax_referer('purr_child_admin', 'nonce');
    if (!current_user_can('manage_options')) {
        wp_send_json_error('Permission denied', 403);
    }
    $action = isset($_POST['operation']) && is_string($_POST['operation'])
        ? sanitize_key(wp_unslash($_POST['operation'])) : '';
    $checks = ['check_registry' => 'registry_versions', 'check_knowledge' => 'knowledge_versions'];
    if (in_array($action, ['check_knowledge', 'sync_knowledge'], true)
        && !purr_child_knowledge_dependency_ready(true)) {
        wp_send_json_error([
            'message' => 'Sophira knowledge services are unavailable. Cached knowledge remains accessible.',
            'reason' => 'dependency_unavailable',
            'data' => purr_child_admin_data(),
        ], 503);
    }
    if (isset($checks[$action])) {
        $ok = purr_child_admin_run_check($checks[$action]);
    } elseif ($action === 'health_check') {
        $ok = purr_child_admin_run_check('network_health');
    } elseif ($action === 'update_registry') {
        $ok = purr_child_admin_update_registry();
    } elseif ($action === 'sync_knowledge') {
        $ok = purr_child_admin_run_check('knowledge');
        if ($ok) {
            $ok = purr_child_admin_run_check('knowledge_versions');
        }
    } else {
        wp_send_json_error('Unsupported action', 400);
    }
    if (!$ok) {
        wp_send_json_error(['message' => 'Operation failed; previous verified data remains available.',
            'data' => purr_child_admin_data()], 503);
    }
    wp_send_json_success(purr_child_admin_data());
});

function purr_child_render_admin(): void {
    if (!current_user_can('manage_options')) return;
    echo '<div class="wrap purr-console">';
    echo '<div class="purr-console-header"><div class="purr-header-mark" aria-hidden="true">✦</div><div>';
    echo '<div class="purr-eyebrow">PROJECT PURRFECT / WORDPRESS</div>';
    echo '<h1>Purr Child <span>Control Center</span></h1>';
    echo '<p>Manage product connections, approved knowledge and network diagnostics.</p>';
    echo '</div><span class="purr-header-version">CHILD NODE</span></div>';
    echo '<nav class="purr-console-tabs" aria-label="Purr Child sections">';
    echo '<button type="button" class="purr-console-tab is-active" data-purr-tab="registry" aria-selected="true">Registry</button>';
    echo '<button type="button" class="purr-console-tab" data-purr-tab="knowledge" aria-selected="false">Knowledge</button>';
    echo '<button type="button" class="purr-console-tab" data-purr-tab="settings" aria-selected="false">Settings</button></nav>';
    echo '<div id="purr-admin-feedback" role="status" aria-live="polite"></div>';
    echo '<section id="purr-admin-registry" class="purr-admin-panel"></section>';
    echo '<section id="purr-admin-knowledge" class="purr-admin-panel" hidden></section>';
    echo '<section id="purr-admin-settings" class="purr-admin-panel" hidden></section></div>';
    wp_enqueue_style('purr-child-admin', plugins_url('../assets/admin.css', __FILE__), [], '0.2.0');
    wp_enqueue_script('purr-child-admin', plugins_url('../assets/admin.js', __FILE__), [], '0.2.1', true);
    wp_add_inline_script('purr-child-admin', 'window.purrChildAdmin=' . wp_json_encode([
        'endpoint' => admin_url('admin-ajax.php'), 'nonce' => wp_create_nonce('purr_child_admin'),
        'initial' => purr_child_admin_data(),
    ]) . ';', 'before');
}
