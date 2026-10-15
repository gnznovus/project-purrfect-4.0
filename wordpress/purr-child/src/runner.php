<?php
/** Called by WordPress bootstrap once per minute via external wall-clock runner. */
defined('ABSPATH') || exit;

add_filter('purrfect/heartbeat_components', 'purr_child_register_heartbeat');
add_action('purrfect/heartbeat_tick', 'purr_child_heartbeat_tick');

function purr_child_dirty_on_change(): void {
    purr_child_heartbeat_dirty('registry');
}
foreach ([
    'activated_plugin', 'deactivated_plugin', 'switch_theme',
    'upgrader_process_complete', 'deleted_plugin', 'deleted_theme',
] as $hook) {
    add_action($hook, 'purr_child_dirty_on_change');
}

// WP-Cron fallback only: the Docker lab uses a traffic-independent system cron.
add_filter('cron_schedules', static function (array $schedules): array {
    $schedules['purr_child_minute'] = [
        'interval' => 60, 'display' => 'Purr Child Heartbeat (minute)',
    ];
    return $schedules;
});
add_action('init', static function (): void {
    if (!wp_next_scheduled('purrfect/heartbeat_tick')) {
        wp_schedule_event(time() + 60, 'purr_child_minute', 'purrfect/heartbeat_tick');
    }
});
register_deactivation_hook(dirname(__DIR__) . '/purr-child.php', static function (): void {
    wp_clear_scheduled_hook('purrfect/heartbeat_tick');
});
