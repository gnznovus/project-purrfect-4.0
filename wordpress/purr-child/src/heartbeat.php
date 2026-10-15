<?php
/** Scheduler-independent heartbeat dispatcher; one clock, independent checks. */
defined('ABSPATH') || exit;

function purr_child_heartbeat_tick(?int $now = null): array {
    $now = $now ?? time();
    $definitions = apply_filters('purrfect/heartbeat_components', []);
    if (!is_array($definitions)) {
        return [];
    }
    $results = [];
    foreach ($definitions as $id => $component) {
        if (!is_string($id) || !preg_match('/^[a-z0-9_-]+$/', $id)
            || !is_array($component) || !isset($component['interval'], $component['callback'])
            || !is_int($component['interval']) || $component['interval'] < 1
            || !is_callable($component['callback'])) {
            continue;
        }
        $interval = $component['interval'];
        $status_key = 'purr_child_heartbeat_' . $id;
        $status = get_option($status_key, []);
        if (!is_array($status)) {
            $status = [];
        }
        $dirty = !empty($status['dirty']);
        $next = (int) ($status['next_due'] ?? 0);
        if (!$dirty && $now < $next) {
            continue;
        }
        $lock = 'purr_child_lock_' . $id;
        if (!add_option($lock, $now, '', false)) {
            $locked_at = (int) get_option($lock, 0);
            // Stale lock recovery; never delete an actively held lock.
            if ($locked_at > 0 && $now - $locked_at > max(300, $interval * 2)) {
                delete_option($lock);
                if (!add_option($lock, $now, '', false)) {
                    continue;
                }
            } else {
                continue;
            }
        }
        try {
            $result = call_user_func($component['callback']);
            if ($result === false || is_wp_error($result)) {
                throw new RuntimeException('Heartbeat component failed');
            }
            // Advance from the scheduled grid, not finish time; skip missed ticks.
            $next_due = $next > 0 ? $next : $now;
            $next_due += (int) (floor(max(0, $now - $next_due) / $interval) + 1) * $interval;
            $status = [
                'last_attempt' => $now,
                'last_success' => $now,
                'next_due' => $next_due,
                'failures' => 0,
                'dirty' => false,
            ];
            $results[$id] = 'success';
        } catch (Throwable $error) {
            $status = [
                'last_attempt' => $now,
                'last_success' => (int) ($status['last_success'] ?? 0),
                'next_due' => $now + min($interval, 300),
                'failures' => (int) ($status['failures'] ?? 0) + 1,
                'dirty' => true,
            ];
            $results[$id] = 'failure';
        } finally {
            update_option($status_key, $status, false);
            delete_option($lock);
        }
    }
    return $results;
}

function purr_child_heartbeat_dirty(string $id): void {
    $key = 'purr_child_heartbeat_' . $id;
    $status = get_option($key, []);
    if (!is_array($status)) {
        $status = [];
    }
    $status['dirty'] = true;
    update_option($key, $status, false);
}

/** Immutable last-good knowledge snapshot; never mark a failed scan as fresh. */
function purr_child_refresh_registry(): bool {
    $discovered = purr_child_discover();
    $serialized = wp_json_encode($discovered);
    if (!is_string($serialized)) {
        return false;
    }
    $digest = hash('sha256', $serialized);
    $current_digest = get_option('purr_child_registry_digest', '');
    if (!hash_equals((string) $current_digest, $digest)) {
        update_option('purr_child_registry', $discovered, false);
        update_option('purr_child_registry_digest', $digest, false);
    }
    return true;
}

function purr_child_register_heartbeat(array $components): array {
    $components['registry'] = [
        'interval' => 300,
        'callback' => 'purr_child_refresh_registry',
    ];
    return $components;
}
