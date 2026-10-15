<?php
/**
 * Plugin Name: Purr Child
 * Description: Local discovery of compatible active WordPress products for Purra.
 * Version: 0.1.0
 * Requires PHP: 8.0
 */

defined('ABSPATH') || exit;

require_once __DIR__ . '/src/discovery.php';

/**
 * Products advertise a signal using the purrfect/product_signals filter.
 *
 * Each signal identifies its installed plugin basename or theme stylesheet,
 * not merely a display name. No information is transmitted off-site here.
 */
add_action('rest_api_init', static function (): void {
    register_rest_route('purrfect/v1', '/discovery', [
        'methods' => 'GET',
        'permission_callback' => static fn(): bool => current_user_can('manage_options'),
        'callback' => static fn() => rest_ensure_response(purr_child_discover()),
    ]);
});
