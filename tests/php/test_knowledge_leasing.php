<?php
/** Focused knowledge lease protocol tests; no WordPress runtime required. */
define('ABSPATH', __DIR__);
require dirname(__DIR__, 2) . '/wordpress/purr-child/src/heartbeat.php';

function check_lease(bool $ok, string $why): void {
    if (!$ok) {
        throw new RuntimeException($why);
    }
}
function make_lease(int $revision, array $items): array {
    $package = [
        'product_id' => 'mock-translation', 'product_version' => '1',
        'revision' => $revision, 'contract_version' => 1, 'digest' => '',
        'items' => $items,
    ];
    usort($items, static fn($a, $b) => strcmp($a['id'], $b['id']));
    $triples = array_map(static fn($i) => [$i['id'], $i['content'], $i['source']], $items);
    $package['digest'] = hash('sha256', json_encode(
        ['mock-translation', '1', $revision, 1, $triples],
        JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
    ));
    return $package;
}
$first = make_lease(1, [
    ['id' => 'a', 'content' => 'one', 'source' => 'mock://a'],
    ['id' => 'b', 'content' => 'two', 'source' => 'mock://b'],
]);
check_lease(purr_child_knowledge_valid($first), 'Valid Python-compatible package rejected');
$bad = $first;
$bad['items'][0]['content'] = 'tampered';
check_lease(!purr_child_knowledge_valid($bad), 'Tampering not detected');
$second = make_lease(2, [
    ['id' => 'a', 'content' => 'updated', 'source' => 'mock://a'],
    ['id' => 'c', 'content' => 'new', 'source' => 'mock://c'],
]);
$delta = [
    'type' => 'delta', 'product_id' => 'mock-translation',
    'product_version' => '1', 'from_revision' => 1, 'to_revision' => 2,
    'upserts' => $second['items'], 'removed_ids' => ['b'],
    'target_digest' => $second['digest'],
];
$updated = purr_child_knowledge_apply($first, $delta);
check_lease(($updated['digest'] ?? null) === $second['digest'], 'Delta checksum invalid');
$bad_delta = $delta;
$bad_delta['target_digest'] = str_repeat('0', 64);
check_lease(purr_child_knowledge_apply($first, $bad_delta) === [], 'Corrupted delta was accepted');
check_lease(purr_child_knowledge_apply($second, $delta) === [], 'Stale delta was accepted');
$initial = ['product_id' => 'mock-translation', 'product_version' => '1', 'revision' => 0, 'items' => []];
check_lease(purr_child_knowledge_apply($initial, [
    'type' => 'snapshot', 'product_id' => 'mock-translation',
    'product_version' => '1', 'payload' => $first,
]) !== [], 'Initial snapshot rejected');
echo "PHP knowledge leasing smoke OK\n";
