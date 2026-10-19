<?php
/** Admin-only Purra chat transport and floating assistant; no legacy lab page. */
defined('ABSPATH') || exit;

add_action('wp_ajax_purr_child_chat', static function (): void {
    check_ajax_referer('purr_child_lab', 'nonce');
    if (!current_user_can('manage_options')) {
        wp_send_json_error('Permission denied', 403);
    }
    $message = isset($_POST['message']) && is_string($_POST['message'])
        ? sanitize_text_field(wp_unslash($_POST['message'])) : '';
    $session = isset($_POST['session']) && is_string($_POST['session'])
        ? sanitize_text_field(wp_unslash($_POST['session'])) : '';
    $selection = isset($_POST['selection']) && is_string($_POST['selection'])
        ? sanitize_text_field(wp_unslash($_POST['selection'])) : null;
    if (strlen($message) > 2000 || strlen($session) > 128 || $session === ''
        || ($selection !== null && (strlen($selection) > 160 || !preg_match('/\\A[a-zA-Z0-9:_-]+\\z/', $selection)))) {
        wp_send_json_error('Invalid request', 400);
    }
    $inventory = get_option('purr_child_registry', []);
    if (!is_array($inventory) || empty($inventory['active'])) {
        wp_send_json_error('Registry is not ready. Wait for the heartbeat.', 503);
    }
    $context = new stdClass();
    if (isset($_POST['context']) && is_string($_POST['context'])) {
        $parsed = json_decode(wp_unslash($_POST['context']), true);
        if (!is_array($parsed) || strlen(wp_unslash($_POST['context'])) > 4096) {
            wp_send_json_error('Invalid context', 400);
        }
        $context = (object) $parsed;
    }
    $response = wp_remote_post('http://purra:8765/v1/chat', [
        'timeout' => 25,
        'headers' => ['Content-Type' => 'application/json'],
        'body' => wp_json_encode([
            'session_id' => $session, 'message' => $message,
            'selection' => $selection, 'inventory' => $inventory,
            'context' => $context,
            'debug' => isset($_POST['debug']) && $_POST['debug'] === '1',
            'knowledge_leases' => array_values(array_filter(
                get_option('purr_child_knowledge_leases', []),
                static fn($lease) => is_array($lease) && purr_child_knowledge_valid($lease)
            )),
        ]),
    ]);
    if (is_wp_error($response)) {
        wp_send_json_error('Purr service is unavailable.', 503);
    }
    $code = wp_remote_retrieve_response_code($response);
    $body = json_decode(wp_remote_retrieve_body($response), true);
    if ($code !== 200 || !is_array($body)) {
        wp_send_json_error('Purr did not return a valid response.', 502);
    }
    wp_send_json_success($body);
});

/** The user-facing Child is available only to authenticated site administrators. */
add_action('admin_footer', static function (): void {
    if (!current_user_can('manage_options')) {
        return;
    }
    echo '<div id="purr-child-widget" aria-label="Purr Assistant"></div>';
});

add_action('admin_enqueue_scripts', static function (): void {
    if (!current_user_can('manage_options')) return;
    wp_enqueue_style('purr-child-widget', plugins_url('../assets/widget.css', __FILE__), [], '0.1.3');
    wp_enqueue_script('purr-child-widget', plugins_url('../assets/widget.js', __FILE__), [], '0.1.9', true);
    wp_add_inline_script('purr-child-widget', 'window.purrChildWidget = ' . wp_json_encode([
        'endpoint' => admin_url('admin-ajax.php'),
        'nonce' => wp_create_nonce('purr_child_lab'),
        'scope' => get_current_blog_id() . ':' . get_current_user_id(),
        'purraAvatar' => plugins_url('../assets/purra-avatar.png', __FILE__),
    ]) . ';', 'before');
});
