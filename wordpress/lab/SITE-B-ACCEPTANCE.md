# Goal 1.9 — Site B live acceptance

Site B is an **additive Compose overlay**. It shares Purra/Sophira with Site A but has separate WordPress data, MariaDB storage, registry, cache and heartbeat. No Site A migrations or volume changes.

Run from repository root in PowerShell.

```powershell
$compose = @('-f', 'wordpress/lab/compose.yaml', '-f', 'wordpress/lab/compose.site-b.yaml')
docker compose @compose --profile brain config --quiet
docker compose @compose --profile brain up -d --no-recreate db_b wp_b clock_b
docker compose @compose ps
```

Open http://localhost:8085/wp-admin/install.php and perform a **fresh Site B setup** with distinct local test credentials. Do not import Site A data. Alternatively, if you prefer WP-CLI, use:

```powershell
docker compose @compose --profile tools run --rm cli_b wp core install --url=http://localhost:8085 --title="Purrfect Lab B" --admin_user=lab_b_admin --admin_email=lab-b@example.test --prompt=admin_password
docker compose @compose --profile tools run --rm cli_b wp plugin activate purr-child mock-translation
```

If Site B is already installed, do not run the install command again. The browser-based setup is simpler for first-run acceptance.

Refresh the registry and knowledge lease **inside Site B** without touching Site A:

```powershell
@'
<?php
require '/var/www/html/wp-load.php';
purr_child_heartbeat_dirty('registry');
purr_child_heartbeat_dirty('knowledge');
echo json_encode(purr_child_heartbeat_tick(), JSON_PRETTY_PRINT), "\n";
echo json_encode(get_option('purr_child_knowledge_leases', []), JSON_PRETTY_PRINT), "\n";
'@ | docker compose @compose exec -T wp_b php
```

Expected: Site B independently leases Sophira's current mock-translation revision. Site A (localhost:8084) stays intact with its own cache. For a new revision, repeat the knowledge heartbeat **separately** on Site A and Site B and compare the revisions and Purra replies.

```powershell
docker compose @compose ps
```

Do not use `down -v`, `docker volume rm`, `prune`, or reset Site A. This overlay never creates a second Sophira database or a second Purra process. To stop only Site B, use `docker compose @compose stop clock_b wp_b db_b`.

**Security scope:** local prototype only; internal sync route has no cross-host authentication yet. Do not expose Docker-internal Purra/Sophira sync endpoints publicly.
