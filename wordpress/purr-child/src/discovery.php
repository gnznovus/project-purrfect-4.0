<?php
/** Local, read-only WordPress component inventory and product signal validation. */

defined('ABSPATH') || exit;

function purr_child_discover(): array {
    if (!function_exists('get_plugins')) {
        require_once ABSPATH . 'wp-admin/includes/plugin.php';
    }
    $active_plugins = (array) get_option('active_plugins', []);
    // Multisite network-active plugins are active too.
    if (is_multisite()) {
        $active_plugins = array_merge(
            $active_plugins,
            array_keys((array) get_site_option('active_sitewide_plugins', []))
        );
    }
    $active_plugins = array_values(array_unique(array_filter(
        $active_plugins, 'is_string'
    )));
    $active = [];
    foreach ($active_plugins as $basename) {
        $active[] = ['kind' => 'plugin', 'key' => $basename];
    }

    $stylesheet = get_stylesheet();
    $template = get_template();
    foreach (array_unique([$stylesheet, $template]) as $theme) {
        if (is_string($theme) && $theme !== '') {
            $active[] = ['kind' => 'theme', 'key' => $theme];
        }
    }

    $allowed = [];
    foreach ($active as $item) {
        $allowed[$item['kind'] . ':' . $item['key']] = true;
    }

    $signals = apply_filters('purrfect/product_signals', []);
    if (!is_array($signals)) {
        $signals = [];
    }
    $accepted = [];
    $seen = [];
    foreach ($signals as $signal) {
        if (!is_array($signal)) {
            continue;
        }
        $fields = ['kind', 'key', 'product_id', 'version', 'contract', 'capabilities', 'knowledge'];
        if (array_diff($fields, array_keys($signal)) || array_diff(array_keys($signal), $fields)) {
            continue;
        }
        $kind = $signal['kind'];
        $key = $signal['key'];
        $id = $signal['product_id'];
        if (!is_string($kind) || !is_string($key) || !is_string($id)
            || !isset($allowed[$kind . ':' . $key]) || $id === ''
            || isset($seen[$id]) || $signal['contract'] !== 1
            || !is_string($signal['version']) || $signal['version'] === ''
            || !is_array($signal['capabilities']) || !is_array($signal['knowledge'])) {
            continue;
        }
        $accepted[] = $signal;
        $seen[$id] = true;
    }

    return ['active' => $active, 'signals' => $accepted];
}
