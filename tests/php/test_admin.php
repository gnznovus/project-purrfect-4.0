<?php
/** Goal 1.10: heartbeat-backed read-only knowledge version-check acceptance. */
define('ABSPATH', __DIR__ . '/');
$GLOBALS['options'] = [];
$GLOBALS['published'] = [];
function get_option($key, $default = false) { return $GLOBALS['options'][$key] ?? $default; }
function update_option($key, $value, $autoload = null) {
    $GLOBALS['options'][$key] = $value;
    return true;
}
function add_option($key, $value, $deprecated = '', $autoload = false) {
    if (array_key_exists($key, $GLOBALS['options'])) return false;
    $GLOBALS['options'][$key] = $value;
    return true;
}
function delete_option($key) { unset($GLOBALS['options'][$key]); return true; }
function is_wp_error($value) { return false; }
function wp_json_encode($value) { return json_encode($value); }
function add_action(...$args) {}
function apply_filters($key, $value) {
    return $key === 'purrfect/heartbeat_components'
        ? purr_child_register_heartbeat($value) : $value;
}
function wp_remote_post($url, $args) {
    $GLOBALS['published'][] = ['url' => $url, 'request' => json_decode($args['body'], true)];
    return ['code' => 200, 'body' => json_encode([
        'contract_version' => 1, 'updates' => [[
            'type' => 'snapshot', 'product_id' => 'mock-translation',
            'product_version' => '1.0.0',
            'payload' => $GLOBALS['remote_package'],
        ]],
    ])];
}
function wp_remote_retrieve_response_code($response) { return $response['code']; }
function wp_remote_retrieve_body($response) { return $response['body']; }
function verify(bool $condition, string $message): void {
    if (!$condition) throw new RuntimeException($message);
}
require dirname(__DIR__, 2) . '/wordpress/purr-child/src/heartbeat.php';
require dirname(__DIR__, 2) . '/wordpress/purr-child/src/admin.php';

$fixture = dirname(__DIR__) . '/fixtures/sophira-mock-rev';
$old = json_decode(file_get_contents($fixture . '2.json'), true);
$GLOBALS['remote_package'] = json_decode(file_get_contents($fixture . '3.json'), true);
verify(purr_child_knowledge_valid($old), 'Legacy r2 cache must remain valid');
verify(purr_child_knowledge_valid($GLOBALS['remote_package']), 'Approved r3 package must be valid');
$GLOBALS['options']['purr_child_registry'] = ['signals' => [
    ['product_id' => 'mock-translation', 'version' => '1.0.0'],
]];
$GLOBALS['options']['purr_child_knowledge_leases'] = ['mock-translation' => $old];
verify(purr_child_admin_run_check('knowledge_versions'), 'Read-only heartbeat version check failed');
$preview = get_option('purr_child_knowledge_version_status', []);
verify(($preview['checked_at'] ?? null) > 0, 'Check time must be stored');
verify(count($preview['rows']) === 2, 'Both entries must be previewed');
$versions = [];
foreach ($preview['rows'] as $row) $versions[$row['id']] = $row;
verify($versions['translation-edit']['latest_revision'] === 2, 'Translation entry should remain r2');
verify($versions['translation-troubleshoot-access']['latest_revision'] === 1, 'Access should start at r1');
verify($versions['translation-troubleshoot-access']['status'] === 'update_available',
    'New access knowledge should be reported');
verify(get_option('purr_child_knowledge_leases')['mock-translation'] === $old,
    'Read-only version check illegally modified local lease');
verify(count($GLOBALS['published']) === 1, 'Check should make exactly one read-only sync query');
verify($GLOBALS['published'][0]['request']['products'][0]['revision'] === 2,
    'Remote version check must advertise existing local revision');
echo "PHP admin read-only knowledge check passed\n";
