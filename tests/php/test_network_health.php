<?php
/** Goal 1.10: independent network probes and last-good lease preservation. */
define('ABSPATH', __DIR__ . '/');
$GLOBALS['options'] = [];
$GLOBALS['sophira_up'] = false;
function get_option($key, $default = false) { return $GLOBALS['options'][$key] ?? $default; }
function update_option($key, $value, $autoload = null) {
    $GLOBALS['options'][$key] = $value;
    return true;
}
function add_action(...$args) {}
function is_wp_error($value) { return false; }
function wp_remote_get($url, $args) {
    if (str_ends_with($url, '/v1/health'))
        return ['code' => 200, 'body' => '{"service":"purra","status":"healthy"}'];
    if (str_ends_with($url, '/v1/knowledge/health') && $GLOBALS['sophira_up'])
        return ['code' => 200, 'body' => '{"service":"sophira","status":"healthy"}'];
    return ['code' => 503, 'body' => '{"service":"sophira","status":"unavailable"}'];
}
function wp_remote_retrieve_response_code($value) { return $value['code']; }
function wp_remote_retrieve_body($value) { return $value['body']; }
function verify(bool $value, string $message) {
    if (!$value) throw new RuntimeException($message);
}
require dirname(__DIR__, 2) . '/wordpress/purr-child/src/heartbeat.php';
require dirname(__DIR__, 2) . '/wordpress/purr-child/src/admin.php';
$cache = json_decode(file_get_contents(dirname(__DIR__) . '/fixtures/sophira-mock-rev2.json'), true);
$GLOBALS['options']['purr_child_knowledge_leases'] = ['mock-translation' => $cache];
$degraded = purr_child_network_health();
verify(!purr_child_knowledge_dependency_ready(true), 'Knowledge actions must be blocked while Sophira sleeps');
verify($degraded['child']['status'] === 'healthy', 'Valid cache must remain healthy');
verify($degraded['purra']['status'] === 'healthy', 'Purra should be available');
verify($degraded['sophira']['status'] === 'unavailable', 'Sophira outage must be reported');
verify(get_option('purr_child_knowledge_leases')['mock-translation'] === $cache,
    'Health probe must not discard last-good knowledge');
$GLOBALS['sophira_up'] = true;
$recovered = purr_child_network_health();
verify(purr_child_knowledge_dependency_ready(true), 'Knowledge actions must recover when Sophira returns');
verify($recovered['sophira']['status'] === 'healthy', 'Sophira recovery not reported');
verify($recovered['purra']['status'] === 'healthy', 'Purra state must remain independent');
echo "PHP network health isolation passed\n";
