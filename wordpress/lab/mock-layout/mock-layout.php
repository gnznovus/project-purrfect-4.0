<?php
/**
 * Plugin Name: Purr Mock Layout
 * Version: 1.0.0
 */
defined('ABSPATH') || exit;
add_filter('purrfect/product_signals', static function (array $signals): array {
    $signals[] = [
        'kind' => 'plugin', 'key' => plugin_basename(__FILE__),
        'product_id' => 'mock-layout', 'version' => '1.0.0', 'contract' => 1,
        'capabilities' => ['edit-layout'],
        'knowledge' => [[
            'id' => 'layout-edit', 'title' => 'Edit layout blocks',
            'text' => 'Open the mock layout panel to edit layout blocks.',
            'source' => 'mock-layout://docs/edit',
            'tags' => ['layout', 'block', 'edit'],
        ]],
    ];
    return $signals;
});
