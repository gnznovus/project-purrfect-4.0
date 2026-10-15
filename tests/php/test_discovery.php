<?php
/** WordPress shim: test inventory behavior without WordPress or an HTTP server. */
define('ABSPATH', __DIR__ . '/');
function get_option($name, $fallback) {
    return $GLOBALS['active_plugins'];
}
function is_multisite() { return $GLOBALS['multisite']; }
function get_site_option($name, $fallback) {
    return $GLOBALS['network_plugins'];
}
function get_stylesheet() { return 'child-theme'; }
function get_template() { return 'parent-theme'; }
function apply_filters($hook, $initial) {
    if ($hook !== 'purrfect/product_signals') { throw new RuntimeException('Unexpected filter'); }
    return $GLOBALS['signals'];
}
function get_plugins() { return []; }
require dirname(__DIR__, 2) . '/wordpress/purr-child/src/discovery.php';

function check($condition, $message) {
    if (!$condition) { throw new RuntimeException($message); }
}
$GLOBALS['active_plugins'] = ['layout/main.php', 'inactive-but-not-listed.php'];
$GLOBALS['multisite'] = true;
$GLOBALS['network_plugins'] = ['network/entry.php' => 123];
$GLOBALS['signals'] = [
    [
        'kind' => 'plugin', 'key' => 'layout/main.php', 'product_id' => 'layout',
        'version' => '1.0', 'contract' => 1, 'capabilities' => ['layout'],
        'knowledge' => [],
    ],
    [
        'kind' => 'theme', 'key' => 'parent-theme', 'product_id' => 'theme',
        'version' => '1.0', 'contract' => 1, 'capabilities' => [],
        'knowledge' => [],
    ],
    [
        'kind' => 'plugin', 'key' => 'not-active/main.php', 'product_id' => 'invalid',
        'version' => '1.0', 'contract' => 1, 'capabilities' => [],
        'knowledge' => [],
    ],
];
$found = purr_child_discover();
check(count($found['active']) === 5, 'Must inventory regular and network plugins and both themes');
check(count($found['signals']) === 2, 'Inactive product must not register');
$GLOBALS['active_plugins'] = ['other/main.php'];
$found = purr_child_discover();
check(count($found['signals']) === 1, 'Deactivated plugin must disappear');
echo "PHP discovery smoke passed\n";
