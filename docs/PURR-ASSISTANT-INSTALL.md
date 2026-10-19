# Purr Assistant — installable WordPress plugin

The WordPress plugin source is `wordpress/purr-child/`. Installable archives
use the top-level plugin directory `PurrAssistant/` and contain
`PurrAssistant/purr-child.php`.

## Build

On Windows, from a checkout of `feat/layout-engine-whoosh`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-purr-assistant.ps1
```

Result: `dist/PurrAssistant.zip`. Do not zip the repository root.

Alternatively, GitHub Actions **Build PurrAssistant ZIP** packages the plugin on
pushes to this feature branch or when launched manually. Download the
`PurrAssistant` artifact from that workflow run and extract the contained
`PurrAssistant.zip`.

## Install on WordPress

In **Plugins → Add New Plugin → Upload Plugin**, select
`PurrAssistant.zip`, install and activate. The widget is currently available
to signed-in administrators, not public visitors.

**The ZIP contains the WordPress plugin, not Purr's Python service, Sophia,
Ollama, or a remote authentication/deployment solution.** On an external
WordPress installation, `http://purra:8765` (the default local Docker
service name) will not resolve. Configure your own reachable, trusted backend
in `wp-config.php`, before WordPress loads plugins:

```php
define('PURR_ASSISTANT_SERVICE_URL', 'https://your-internal-purr-service.example');
```

The setting is the **base URL**. Purr Assistant appends `/v1/chat` and
`/v1/knowledge/sync`. Use a reachable host from the **WordPress PHP server**
(not just the browser). Ensure the backend and its permissions are configured
before attempting a live conversation.

## Safety / current status

This is a development integration build, **not a production deployment**.
The current Purr service integration uses a lab-oriented trust model; do not
expose the backend openly to the Internet. Cross-host authentication,
TLS/reverse-proxy configuration, and real-site acceptance remain outstanding.

Whoosh locations require a compatible active product (such as the matching
Layout Engine feature branch), the latest product registry, and an approved
Yes/No action. No Yes click means no navigation.

## Rebuild after changes

Run the PowerShell build command again after updating your checkout. The ZIP
reflects the exact files of the current checked-out branch.
