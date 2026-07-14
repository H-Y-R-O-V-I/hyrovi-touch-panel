# Update System

Das Projekt benutzt ein Release-Modell:

- `/opt/hyrovi-touch-panel/releases/<release>`
- `/opt/hyrovi-touch-panel/current`
- `/opt/hyrovi-touch-panel/previous`

## Ablauf

1. GitHub-Tags werden geprüft.
2. Wenn Tags vorhanden sind, wird der neueste Tag geladen.
3. Wenn keine Tags vorhanden sind, fällt das System auf `main` zurück.
4. Der neue Stand wird in einen separaten Release-Ordner geklont.
5. Die Dependencies werden in die gemeinsame venv installiert.
6. Die Services werden neu gestartet.
7. Ein Healthcheck entscheidet über den Erfolg.
8. Bei Fehlern wird auf `previous` zurückgerollt.

## Manuell aktualisieren

```bash
hyrovi-panel update
```

## Rollback

```bash
hyrovi-panel rollback
```

## Hinweis zu Tags

Tags sind die bevorzugte Update-Quelle. Wenn das Repo noch keine Tags hat, verwendet das System `main`.
