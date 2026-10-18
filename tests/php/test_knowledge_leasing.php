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
    $triples = array_map(static function ($i) {
        $data = [$i['id'], $i['content'], $i['source']];
        if (isset($i['entry_revision'])) {
            $data[] = $i['entry_revision'];
            $data[] = $i['change_note'] ?? null;
        }
        return $data;
    }, $items);
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
check_lease(purr_child_knowledge_valid($first), 'Valid PHP package rejected');
$python_encoded = json_decode(json_encode($first, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), true);
foreach ($python_encoded['items'] as &$item) {
    ksort($item);
}
unset($item);
ksort($python_encoded);
check_lease(purr_child_knowledge_valid($python_encoded), 'Canonical Python JSON key order rejected');
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


$versioned = make_lease(3, [
    ['id' => 'a', 'content' => 'approved refinement',
     'source' => 'mock-translation://docs/troubleshoot/access',
     'entry_revision' => 2, 'change_note' => 'Clarified access troubleshooting'],
    ['id' => 'c', 'content' => 'new',
     'source' => 'mock://c'],
]);
check_lease(purr_child_knowledge_valid($versioned), 'Versioned checksum rejected');
$changed_note = $versioned;
$changed_note['items'][0]['change_note'] = 'tampered';
check_lease(!purr_child_knowledge_valid($changed_note), 'Changelog tampering not detected');
$versioned_delta = [
    'type' => 'delta', 'product_id' => 'mock-translation',
    'product_version' => '1', 'from_revision' => 2, 'to_revision' => 3,
    'upserts' => [$versioned['items'][0]], 'removed_ids' => [],
    'target_digest' => $versioned['digest'],
];
$versioned_applied = purr_child_knowledge_apply($second, $versioned_delta);
check_lease(($versioned_applied['digest'] ?? null) === $versioned['digest'],
    'Versioned delta checksum invalid');
echo "PHP knowledge leasing and per-entry revision smoke OK\n";
