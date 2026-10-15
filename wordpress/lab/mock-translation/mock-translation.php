<?php
/**
 * Plugin Name: Purr Mock Translation
 * Version: 1.0.0
 */
defined('ABSPATH') || exit;
add_filter('purrfect/product_signals', static function (array $signals): array {
    $signals[] = [
        'kind' => 'plugin', 'key' => plugin_basename(__FILE__),
        'product_id' => 'mock-translation', 'version' => '1.0.0', 'contract' => 1,
        'capabilities' => ['translate-content'],
        'knowledge' => [[
            'id' => 'translation-edit', 'title' => 'Translate content blocks',
            'text' => 'Open the mock translation panel to translate content.',
            'source' => 'mock-translation://docs/edit',
            'tags' => ['translation', 'content', 'translate'],
        ]],
    ];
    return $signals;
});
