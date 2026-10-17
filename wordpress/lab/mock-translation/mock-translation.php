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
        ], [
            'id' => 'translation-troubleshoot-panel', 'title' => 'Translation panel checks',
            'text' => 'If the mock translation panel is missing, first verify that the Mock Translation plugin is active in Plugins.',
            'source' => 'mock-translation://docs/troubleshoot/panel',
            'tags' => ['translation', 'panel', 'missing', 'plugin'],
        ], [
            'id' => 'translation-troubleshoot-access', 'title' => 'Translation panel access check',
            'text' => 'If the panel still cannot be opened, confirm that you are signed into WordPress as an administrator. Do not change permissions without administrator approval.',
            'source' => 'mock-translation://docs/troubleshoot/access',
            'tags' => ['translation', 'panel', 'access', 'administrator'],
        ]],
        'troubleshooting' => [[
            'id' => 'translation-panel-unavailable',
            'title' => 'Mock translation panel is unavailable',
            'steps' => [
                ['id' => 'verify-plugin-active',
                 'instruction' => 'Check whether Mock Translation is active in WordPress Plugins.',
                 'evidence_id' => 'translation-troubleshoot-panel'],
                ['id' => 'verify-admin-session',
                 'instruction' => 'Check whether you are signed in as a WordPress administrator. Do not change roles or permissions.',
                 'evidence_id' => 'translation-troubleshoot-access'],
            ],
        ]],
    ];
    return $signals;
});
