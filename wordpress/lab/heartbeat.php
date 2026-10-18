<?php
/** Entrypoint for the Docker cron service; WordPress must already be installed. */
require '/var/www/html/wp-load.php';
if (!function_exists('purr_child_heartbeat_tick')) {
    exit(0);
}
do_action('purrfect/heartbeat_tick');
