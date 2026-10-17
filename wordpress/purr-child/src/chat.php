<?php
/** Local POC admin chat. WordPress remains the only browser-facing server. */
defined('ABSPATH') || exit;

add_action('admin_menu', static function (): void {
    add_menu_page('Purr Child Lab', 'Purr Child Lab', 'manage_options',
        'purr-child-lab', 'purr_child_render_chat', 'dashicons-format-chat');
});

function purr_child_render_chat(): void {
    if (!current_user_can('manage_options')) {
        return;
    }
    echo '<div class="wrap"><h1>Purr Child — Local Bridge Lab</h1>';
    echo '<p>Local proof of concept using the registered mock products.</p>';
    echo '<div id="purr-child-chat" style="max-width:720px;background:#fff;border:1px solid #ddd;padding:16px">';
    echo '<div id="purr-log" style="min-height:140px;max-height:420px;overflow:auto;white-space:pre-wrap"></div>';
    echo '<div id="purr-options"></div>';
    echo '<p><input id="purr-question" style="width:78%" aria-label="Ask Purra" placeholder="Ask about a product or WordPress" /> ';
    echo '<button id="purr-send" class="button button-primary">Send</button></p></div></div>';
    wp_enqueue_script('purr-child-chat', plugins_url('../assets/chat.js', __FILE__), [], '0.1.1', true);
    wp_add_inline_script('purr-child-chat', 'window.purrChildLab = ' . wp_json_encode([
        'endpoint' => admin_url('admin-ajax.php'),
        'nonce' => wp_create_nonce('purr_child_lab'),
    ]) . ';', 'before');
}

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
        ? sanitize_key(wp_unslash($_POST['selection'])) : null;
    if (strlen($message) > 2000 || strlen($session) > 128 || $session === '') {
        wp_send_json_error('Invalid request', 400);
    }
    $inventory = get_option('purr_child_registry', []);
    if (!is_array($inventory) || empty($inventory['active'])) {
        wp_send_json_error('Registry is not ready. Wait for the heartbeat.', 503);
    }
    $response = wp_remote_post('http://purra:8765/v1/chat', [
        'timeout' => 8,
        'headers' => ['Content-Type' => 'application/json'],
        'body' => wp_json_encode([
            'session_id' => $session, 'message' => $message,
            'selection' => $selection, 'inventory' => $inventory,
        ]),
    ]);
    if (is_wp_error($response)) {
        wp_send_json_error('Local Purra service is unavailable.', 503);
    }
    $code = wp_remote_retrieve_response_code($response);
    $body = json_decode(wp_remote_retrieve_body($response), true);
    if ($code !== 200 || !is_array($body)) {
        wp_send_json_error('Purra did not return a valid response.', 502);
    }
    wp_send_json_success($body);
});
