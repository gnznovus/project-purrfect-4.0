<?php
/** Scheduler-independent heartbeat dispatcher; one clock, independent checks. */
defined('ABSPATH') || exit;

function purr_child_heartbeat_tick(?int $now = null, ?array $only = null): array {
    $now = $now ?? time();
    $definitions = apply_filters('purrfect/heartbeat_components', []);
    if (!is_array($definitions)) {
        return [];
    }
    $results = [];
    foreach ($definitions as $id => $component) {
        if ($only !== null && !in_array($id, $only, true)) continue;
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
    $components['knowledge'] = [
        'interval' => 21600,
        'callback' => 'purr_child_sync_knowledge',
    ];
    $components['network_health'] = [
        'interval' => 60,
        'callback' => 'purr_child_heartbeat_network_health',
    ];
    $components['registry_versions'] = [
        'interval' => 21600,
        'callback' => 'purr_child_check_registry_versions',
    ];
    $components['knowledge_versions'] = [
        'interval' => 21600,
        'callback' => 'purr_child_check_knowledge_versions',
    ];
    return $components;
}

/** Validate Sophira's canonical SHA-256 package independently in the Child. */
function purr_child_knowledge_valid(array $package): bool {
    $fields = array_keys($package);
    sort($fields);
    if ($fields !== ['contract_version', 'digest', 'items', 'product_id', 'product_version', 'revision']) {
        return false;
    }
    if (!is_string($package['product_id']) || !is_string($package['product_version'])
        || !is_int($package['revision']) || $package['revision'] < 1
        || ($package['contract_version'] ?? null) !== 1
        || !is_string($package['digest']) || !is_array($package['items'])) {
        return false;
    }
    $items = $package['items'];
    if (count($items) > 1000) {
        return false;
    }
    $seen = [];
    foreach ($items as $item) {
        if (!is_array($item) || !in_array(count($item), [3, 5], true)
            || !array_key_exists('id', $item) || !array_key_exists('content', $item)
            || !array_key_exists('source', $item)
            || (count($item) === 5 && (!array_key_exists('entry_revision', $item)
                || !array_key_exists('change_note', $item)
                || !is_int($item['entry_revision']) || $item['entry_revision'] < 1
                || ($item['change_note'] !== null && (!is_string($item['change_note'])
                    || trim($item['change_note']) === ''))))
            || count(array_diff(array_keys($item), ['id', 'content', 'source', 'entry_revision', 'change_note'])) !== 0
            || !is_string($item['id']) || $item['id'] === ''
            || !is_string($item['content']) || $item['content'] === ''
            || !is_string($item['source']) || $item['source'] === ''
            || isset($seen[$item['id']])) {
            return false;
        }
        $seen[$item['id']] = true;
    }
    usort($items, static fn($a, $b) => strcmp($a['id'], $b['id']));
    $triples = array_map(static function($i) {
        $record = [$i['id'], $i['content'], $i['source']];
        if (array_key_exists('entry_revision', $i)) {
            $record[] = $i['entry_revision'];
            $record[] = $i['change_note'];
        }
        return $record;
    }, $items);
    $canonical = json_encode([
        $package['product_id'], $package['product_version'], $package['revision'],
        $package['contract_version'], $triples,
    ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    return is_string($canonical) && hash_equals($package['digest'], hash('sha256', $canonical));
}

/** Apply an update privately, committing only a complete verified replacement. */
function purr_child_knowledge_apply(array $current, array $update): array {
    $pid = $update['product_id'] ?? null;
    $version = $update['product_version'] ?? null;
    if (!is_string($pid) || !is_string($version) || !isset($current['product_id'])
        || $current['product_id'] !== $pid || $current['product_version'] !== $version) {
        return [];
    }
    if (($update['type'] ?? null) === 'snapshot') {
        $next = $update['payload'] ?? null;
        if (!is_array($next) || $next['product_id'] !== $pid || $next['product_version'] !== $version
            || !is_int($next['revision']) || $next['revision'] <= $current['revision']) {
            return [];
        }
    } elseif (($update['type'] ?? null) === 'delta') {
        if (($update['from_revision'] ?? null) !== $current['revision']
            || !is_int($update['to_revision'] ?? null) || $update['to_revision'] <= $current['revision']
            || !is_array($update['removed_ids'] ?? null) || !is_array($update['upserts'] ?? null)
            || !is_string($update['target_digest'] ?? null)) {
            return [];
        }
        $items = [];
        foreach ($current['items'] as $item) {
            $items[$item['id']] = $item;
        }
        foreach ($update['removed_ids'] as $id) {
            if (!is_string($id) || !array_key_exists($id, $items)) {
                return [];
            }
            unset($items[$id]);
        }
        foreach ($update['upserts'] as $item) {
            if (!is_array($item) || !is_string($item['id'] ?? null)) {
                return [];
            }
            $items[$item['id']] = $item;
        }
        $next = [
            'product_id' => $pid, 'product_version' => $version,
            'revision' => $update['to_revision'], 'contract_version' => 1,
            'digest' => $update['target_digest'], 'items' => array_values($items),
        ];
    } else {
        return [];
    }
    return purr_child_knowledge_valid($next) ? $next : [];
}

/** Existing site-owned heartbeat. Retry failures without deleting last-good leases. */
function purr_child_sync_knowledge(): bool {
    $registry = get_option('purr_child_registry', []);
    if (!is_array($registry) || !is_array($registry['signals'] ?? null)) {
        return false;
    }
    $stored = get_option('purr_child_knowledge_leases', []);
    if (!is_array($stored)) {
        $stored = [];
    }
    $products = [];
    $active = [];
    foreach ($registry['signals'] as $signal) {
        if (!is_array($signal) || !is_string($signal['product_id'] ?? null)
            || !is_string($signal['version'] ?? null)) {
            continue;
        }
        $pid = $signal['product_id'];
        $version = $signal['version'];
        $active[$pid] = $version;
        $lease = $stored[$pid] ?? null;
        if (is_array($lease) && $lease['product_version'] === $version
            && purr_child_knowledge_valid($lease)) {
            $revision = $lease['revision'];
        } else {
            $revision = null;
            unset($stored[$pid]);
        }
        $products[] = ['id' => $pid, 'version' => $version, 'revision' => $revision];
    }
    if (!$products) {
        return true;
    }
    $response = wp_remote_post(rtrim(PURR_ASSISTANT_SERVICE_URL, '/') . '/v1/knowledge/sync', [
        'timeout' => 20,
        'headers' => ['Content-Type' => 'application/json'],
        'body' => wp_json_encode(['products' => $products]),
    ]);
    if (is_wp_error($response) || wp_remote_retrieve_response_code($response) !== 200) {
        return false;
    }
    $body = json_decode(wp_remote_retrieve_body($response), true);
    if (!is_array($body) || ($body['contract_version'] ?? null) !== 1
        || !is_array($body['updates'] ?? null)) {
        return false;
    }
    $candidate = $stored;
    foreach ($body['updates'] as $update) {
        if (!is_array($update) || !is_string($update['product_id'] ?? null)) {
            return false;
        }
        $pid = $update['product_id'];
        $version = $active[$pid] ?? null;
        if ($version === null || ($update['product_version'] ?? null) !== $version) {
            return false;
        }
        $previous = $candidate[$pid] ?? null;
        if (($update['type'] ?? null) === 'snapshot' && $previous === null) {
            $previous = [
                'product_id' => $pid, 'product_version' => $version,
                'revision' => 0, 'items' => [],
            ];
        }
        if (!is_array($previous)) {
            return false;
        }
        $next = purr_child_knowledge_apply($previous, $update);
        if (!$next) {
            return false;
        }
        $candidate[$pid] = $next;
    }
    foreach ($candidate as $pid => $lease) {
        if (!isset($active[$pid]) || $lease['product_version'] !== $active[$pid]) {
            unset($candidate[$pid]);
        }
    }
    if ($candidate !== $stored) {
        update_option('purr_child_knowledge_leases', $candidate, false);
    }
    return true;
}
