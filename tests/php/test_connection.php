<?php
/** Portable Assistant identity and offline API settings contract smoke test. */
define('ABSPATH', __DIR__ . '/');
$GLOBALS['options'] = [];
class WP_Error {
    private string $code;
    private string $message;
    public function __construct(string $code, string $message) { $this->code = $code; $this->message = $message; }
    public function get_error_message(): string { return $this->message; }
}
function is_wp_error($value): bool { return $value instanceof WP_Error; }
function add_action(...$args): void {}
function register_activation_hook(...$args): void {}
function get_option($key, $default = false) { return $GLOBALS['options'][$key] ?? $default; }
function add_option($key, $value, $deprecated = '', $autoload = false): bool {
    if (array_key_exists($key, $GLOBALS['options'])) return false;
    $GLOBALS['options'][$key] = $value;
    return true;
}
function update_option($key, $value, $autoload = false): bool {
    $GLOBALS['options'][$key] = $value;
    return true;
}
function wp_parse_url($url) { return parse_url($url); }
function untrailingslashit($value) { return rtrim($value, '/'); }
function verify(bool $condition, string $message): void {
    if (!$condition) throw new RuntimeException($message);
}
require dirname(__DIR__, 2) . '/wordpress/purr-child/src/connection.php';

$id = purr_child_assistant_id();
verify((bool) preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $id), 'Must generate RFC 9562 UUIDv7');
verify(purr_child_assistant_id() === $id, 'Identity must persist across requests');
verify($GLOBALS['options']['purr_child_assistant_id'] === $id, 'Identity must persist in option storage');
verify(purr_child_connection_settings()['pairing_status'] === 'not_paired', 'No fake pairing');
verify(purr_child_validate_api_endpoint('https://purr.example.com/') === 'https://purr.example.com', 'Valid offline HTTPS endpoint');
foreach (['http://purr.example.com', 'https://user:pass@purr.example.com', 'https://purr.example.com/?q=1', 'javascript:alert(1)'] as $bad) {
    verify(is_wp_error(purr_child_validate_api_endpoint($bad)), 'Must reject unsafe endpoint: ' . $bad);
}
$GLOBALS['options']['purr_child_assistant_id'] = 'not-a-uuid';
verify(purr_child_assistant_id() === '', 'Malformed persisted identity must not be silently replaced');
echo "Standalone Assistant identity tests passed.\n";
