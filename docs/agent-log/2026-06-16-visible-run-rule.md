# Visible Run Rule

Дата: 2026-06-16

Закреплено правило пользователя:

- Любой длительный прогон, collector, backtest, replay, grid-search, paper-forward или процесс, который пишет артефакты во времени, запускать только в видимом терминале или через видимый monitor-скрипт.
- Никаких фоновых/скрытых запусков по умолчанию.
- Если задача короткая или несущественная и фон может быть уместен, сначала спросить пользователя: фон или терминал.
- Если пользователь явно разрешил фон, сохранять metadata: PID, command, cwd, stdout, stderr, output/manifest paths, start time, expected duration; сразу дать команду проверки статуса.
- Для молчаливых команд использовать monitor-скрипт с progress, line count, last write, stderr и ошибками.

Файлы политики:

- Global: C:\Users\koval\.codex\AGENTS.md
- Project: C:\Users\koval\Documents\ZolotyayLopata\AGENTS.md
- Memory: C:\Users\koval\.codex\memories\visible-run-rule.md
