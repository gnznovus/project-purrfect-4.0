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
                'product_id' => $pid, 'id' => $item['id'],
                'source' => $item['source'],
                'revision' => $prior['entry_revision'] ?? null,
                'latest_revision' => $item['entry_revision'] ?? null,
                'status' => $newer ? 'update_available' : 'up_to_date',
            ];
            unset($local_items[$item['id']]);
        }
        foreach ($local_items as $item) {
            $rows[] = [
                'product_id' => $pid, 'id' => $item['id'], 'source' => $item['source'],
                'revision' => $item['entry_revision'] ?? null, 'latest_revision' => null,
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

function purr_child_admin_data(): array {
    $registry = get_option('purr_child_registry_version_status', []);
    $knowledge = get_option('purr_child_knowledge_version_status', []);
    $health = [];
    foreach (['registry', 'registry_versions', 'knowledge', 'knowledge_versions'] as $id) {
        $health[$id] = get_option('purr_child_heartbeat_' . $id, []);
    }
    return [
        'registry' => is_array($registry) ? $registry : [],
        'knowledge' => is_array($knowledge) ? $knowledge : [],
        'heartbeat' => $health,
        'plugin_version' => get_file_data(dirname(__DIR__) . '/purr-child.php', ['Version' => 'Version'])['Version'],
    ];
}

add_action('admin_menu', static function (): void {
    add_submenu_page('purr-child-lab', 'Purr Child Administration', 'Administration',
        'manage_options', 'purr-child-admin', 'purr_child_render_admin');
});

add_action('wp_ajax_purr_child_admin_action', static function (): void {
    check_ajax_referer('purr_child_admin', 'nonce');
    if (!current_user_can('manage_options')) {
        wp_send_json_error('Permission denied', 403);
    }
    $action = isset($_POST['operation']) && is_string($_POST['operation'])
        ? sanitize_key(wp_unslash($_POST['operation'])) : '';
    $checks = ['check_registry' => 'registry_versions', 'check_knowledge' => 'knowledge_versions'];
    if (isset($checks[$action])) {
        $ok = purr_child_admin_run_check($checks[$action]);
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
        wp_send_json_error(['message' => 'Check failed; last-good knowledge remains unchanged.',
            'data' => purr_child_admin_data()], 503);
    }
    wp_send_json_success(purr_child_admin_data());
});

function purr_child_render_admin(): void {
    if (!current_user_can('manage_options')) return;
    echo '<div class="wrap"><h1>Purr Child — Administration</h1>';
    echo '<nav class="nav-tab-wrapper"><a href="#registry" class="nav-tab nav-tab-active" data-purr-tab="registry">Registry</a>';
    echo '<a href="#knowledge" class="nav-tab" data-purr-tab="knowledge">Knowledge</a>';
    echo '<a href="#settings" class="nav-tab" data-purr-tab="settings">Settings</a></nav>';
    echo '<div id="purr-admin-registry" class="purr-admin-panel"></div>';
    echo '<div id="purr-admin-knowledge" class="purr-admin-panel" hidden></div>';
    echo '<div id="purr-admin-settings" class="purr-admin-panel" hidden></div></div>';
    wp_enqueue_script('purr-child-admin', plugins_url('../assets/admin.js', __FILE__), [], '0.1.0', true);
    wp_add_inline_script('purr-child-admin', 'window.purrChildAdmin=' . wp_json_encode([
        'endpoint' => admin_url('admin-ajax.php'), 'nonce' => wp_create_nonce('purr_child_admin'),
        'initial' => purr_child_admin_data(),
    ]) . ';', 'before');
}
