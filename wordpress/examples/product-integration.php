<?php
/**
 * EXAMPLE ONLY — add this hook in a participating plugin, not as a separate plugin.
 * Plugin basename and version must describe the actual installed product.
 */
add_filter('purrfect/product_signals', static function (array $signals): array {
    $signals[] = [
        'kind' => 'plugin',
        'key' => plugin_basename(__FILE__), // Replace with the MAIN plugin file basename.
        'product_id' => 'example-product',
        'version' => '1.0.0',
        'contract' => 1,
        'capabilities' => ['page-layout'],
        'knowledge' => [
            [
                'id' => 'layout-edit',
                'title' => 'Edit page layout',
                'text' => 'Open the product layout editor for a supported template.',
                'source' => 'example-product://docs/layout-edit',
                'tags' => ['layout', 'edit', 'template'],
            ],
        ],
    ];
    return $signals;
});
