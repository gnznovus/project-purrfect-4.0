<?php
/** Clock, schedule, and failure-isolation tests without WordPress bootstrap. */
define('ABSPATH', __DIR__ . '/');
$GLOBALS['options'] = [];
$GLOBALS['components'] = [];
$GLOBALS['calls'] = [];
function get_option($key, $default = false) {
    return $GLOBALS['options'][$key] ?? $default;
}
function add_option($key, $value, $deprecated = '', $autoload = false) {
    if (array_key_exists($key, $GLOBALS['options'])) { return false; }
    $GLOBALS['options'][$key] = $value;
    return true;
}
function update_option($key, $value, $autoload = null) {
    $GLOBALS['options'][$key] = $value;
    return true;
}
function delete_option($key) {
    unset($GLOBALS['options'][$key]);
    return true;
}
function apply_filters($name, $default) {
    return $name === 'purrfect/heartbeat_components' ? $GLOBALS['components'] : $default;
}
function is_wp_error($value) { return false; }
function wp_json_encode($value) { return json_encode($value); }
function purr_child_discover() { return $GLOBALS['snapshot']; }
function verify($ok, $message) {
    if (!$ok) { throw new RuntimeException($message); }
}
require dirname(__DIR__, 2) . '/wordpress/purr-child/src/heartbeat.php';

$GLOBALS['components'] = [
    'fast' => ['interval' => 60, 'callback' => function () {
        $GLOBALS['calls'][] = 'fast';
        return true;
    }],
    'slow' => ['interval' => 300, 'callback' => function () {
        $GLOBALS['calls'][] = 'slow';
        return true;
    }],
    'broken' => ['interval' => 60, 'callback' => function () {
        throw new RuntimeException('Expected failure');
    }],
];
$first = purr_child_heartbeat_tick(1000);
verify($first === ['fast' => 'success', 'slow' => 'success', 'broken' => 'failure'],
    'One failed component must not block the rest');
verify(count($GLOBALS['calls']) === 2, 'Each initial component must run once');
verify(purr_child_heartbeat_tick(1020) === ['broken' => 'failure'],
    'Healthy components must honor independent intervals');
verify(purr_child_heartbeat_tick(1060)['fast'] === 'success',
    'Fast component must run when due');
verify(!isset(purr_child_heartbeat_tick(1060)['slow']),
    'Slow component must not run too early');
verify(purr_child_heartbeat_tick(1300)['slow'] === 'success',
    'Slow component must catch up once after downtime');

purr_child_heartbeat_dirty('slow');
verify(purr_child_heartbeat_tick(1301)['slow'] === 'success',
    'Dirty signal must bypass component interval');

$GLOBALS['options']['purr_child_lock_fast'] = 1301;
verify(!isset(purr_child_heartbeat_tick(1360)['fast']),
    'An active lock must prevent overlap');
$GLOBALS['options']['purr_child_lock_fast'] = 1;
verify(purr_child_heartbeat_tick(1361)['fast'] === 'success',
    'Expired abandoned locks must recover');

$GLOBALS['snapshot'] = ['active' => [], 'signals' => []];
verify(purr_child_refresh_registry() === true, 'Initial registry refresh');
$digest = get_option('purr_child_registry_digest');
verify($digest !== '', 'Digest must be stored');
verify(purr_child_refresh_registry() === true, 'Unchanged registry should succeed');
verify($digest === get_option('purr_child_registry_digest'), 'Identical registry digest');
$GLOBALS['snapshot']['active'][] = ['kind' => 'plugin', 'key' => 'mock/main.php'];
purr_child_refresh_registry();
verify($digest !== get_option('purr_child_registry_digest'), 'Activation must update digest');
// An explicitly targeted manual check must NEVER fire another due component.
$GLOBALS['components']['read_only'] = [
    'interval' => 60,
    'callback' => static function (): bool {
        $GLOBALS['calls'][] = 'read_only';
        return true;
    },
];
$GLOBALS['components']['mutating'] = [
    'interval' => 60,
    'callback' => static function (): bool {
        $GLOBALS['calls'][] = 'mutating';
        return true;
    },
];
$before = count($GLOBALS['calls']);
$manual = purr_child_heartbeat_tick(2000, ['read_only']);
verify($manual === ['read_only' => 'success'],
    'Targeted version check must not run other due components');
verify(array_slice($GLOBALS['calls'], $before) === ['read_only'],
    'Targeted check unexpectedly triggered a mutating callback');
echo "Heartbeat tests passed\n";

// Real WordPress invokes action listeners without a timestamp argument.
// Its hook dispatcher can supply an empty string, so the runner must use
// a no-argument adapter rather than registering the typed clock directly.
$GLOBALS['actions'] = [];
function add_action($name, $callback, $priority = 10, $accepted_args = 1) {
    $GLOBALS['actions'][$name][] = $callback;
}
function do_action($name, ...$args) {
    foreach ($GLOBALS['actions'][$name] ?? [] as $callback) {
        $callback(...($args ?: ['']));
    }
}
function add_filter($name, $callback) {}
function register_deactivation_hook($path, $callback) {}
function wp_next_scheduled($hook) { return 1; }
function wp_clear_scheduled_hook($hook) {}
require dirname(__DIR__, 2) . '/wordpress/purr-child/src/runner.php';
verify(isset($GLOBALS['actions']['purrfect/heartbeat_tick']),
    'Heartbeat action must be registered');
do_action('purrfect/heartbeat_tick');
echo "WordPress no-argument hook regression passed\\n";
