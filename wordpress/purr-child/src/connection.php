<?php
/** Standalone Purr Assistant installation identity and future API settings. */
defined('ABSPATH') || exit;

/** RFC 9562 UUIDv7 using a millisecond timestamp and CSPRNG. */
function purr_child_uuid_v7(): string {
    $ms = (int) floor(microtime(true) * 1000);
    $bytes = random_bytes(16);
    for ($i = 5; $i >= 0; $i--) {
        $bytes[$i] = chr($ms & 0xff);
        $ms = intdiv($ms, 256);
    }
    $bytes[6] = chr((ord($bytes[6]) & 0x0f) | 0x70);
    $bytes[8] = chr((ord($bytes[8]) & 0x3f) | 0x80);
    $hex = bin2hex($bytes);
    return substr($hex, 0, 8) . '-' . substr($hex, 8, 4) . '-' .
        substr($hex, 12, 4) . '-' . substr($hex, 16, 4) . '-' . substr($hex, 20);
}

/** Creating an ID is NOT pairing or server-side registration. */
function purr_child_assistant_id(): string {
    $stored = get_option('purr_child_assistant_id', '');
    if (is_string($stored) && preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $stored)) {
        return $stored;
    }
    // Never replace an existing malformed identity silently.
    if ($stored !== '' && $stored !== false) {
        return '';
    }
    $generated = purr_child_uuid_v7();
    if (add_option('purr_child_assistant_id', $generated, '', false)) {
        return $generated;
    }
    $concurrent = get_option('purr_child_assistant_id', '');
    return is_string($concurrent) ? $concurrent : '';
}
register_activation_hook(dirname(__DIR__) . '/purr-child.php', 'purr_child_assistant_id');

/** Saved endpoint is configuration only. It never claims active pairing. */
function purr_child_connection_settings(): array {
    return [
        'assistant_id' => purr_child_assistant_id(),
        'api_endpoint' => (string) get_option('purr_child_api_endpoint', ''),
        'pairing_status' => 'not_paired',
    ];
}

function purr_child_validate_api_endpoint(string $value): string|WP_Error {
    $value = trim($value);
    if ($value === '') return '';
    if (strlen($value) > 2048 || preg_match('/[\\x00-\\x20\\x7f]/', $value)) {
        return new WP_Error('invalid_endpoint', 'Enter a valid API endpoint.');
    }
    $parts = wp_parse_url($value);
    if (!is_array($parts) || strtolower((string) ($parts['scheme'] ?? '')) !== 'https'
        || empty($parts['host']) || isset($parts['user']) || isset($parts['pass'])
        || isset($parts['query']) || isset($parts['fragment'])) {
        return new WP_Error('invalid_endpoint', 'Use an HTTPS API base URL without credentials, query or fragment.');
    }
    $normalized = untrailingslashit($value);
    if (!wp_http_validate_url($normalized)) {
        return new WP_Error('invalid_endpoint', 'The API endpoint must be a valid public HTTPS address.');
    }
    return $normalized;
}

add_action('wp_ajax_purr_child_save_connection', static function (): void {
    check_ajax_referer('purr_child_admin', 'nonce');
    if (!current_user_can('manage_options')) {
        wp_send_json_error('Permission denied', 403);
    }
    $raw = isset($_POST['api_endpoint']) && is_string($_POST['api_endpoint'])
        ? wp_unslash($_POST['api_endpoint']) : '';
    $url = purr_child_validate_api_endpoint($raw);
    if (is_wp_error($url)) {
        wp_send_json_error($url->get_error_message(), 400);
    }
    update_option('purr_child_api_endpoint', $url, false);
    wp_send_json_success(purr_child_connection_settings());
});
