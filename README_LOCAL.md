# Локальный запуск

## Windows

Установите Git и [uv](https://docs.astral.sh/uv/getting-started/installation/), затем:

```powershell
git clone https://github.com/Vangardo/content_radar.git
cd content_radar
.\setup.ps1
.\.venv\Scripts\python.exe -X utf8 -m app.local_setup
.\start.ps1
```

Скрипт создаёт `.venv` с Python 3.11.15 и закреплёнными зависимостями.
`local_setup` создаёт вход `admin` со случайным паролем, который показывает один раз.
Сохраните его. Повторная настройка входа не заменяет существующий пароль.
Откройте http://127.0.0.1:8877. Остановка сервера — Ctrl+C.

Если PowerShell запрещает скрипты, выполните те же действия напрямую:

```powershell
uv venv --python 3.11.15 .venv
uv pip sync --python .venv/Scripts/python.exe requirements-local.lock
.\.venv\Scripts\python.exe -X utf8 -m app.local_setup
.\.venv\Scripts\python.exe -X utf8 -m app
```

Не запускайте setup поверх работающего приложения. При обновлении остановите сервер,
сделайте резервную копию данных, получите код релиза, синхронизируйте зависимости
командой `uv pip sync` и снова запустите приложение.

## Первый поиск

1. Создайте Google Cloud project, включите **YouTube Data API v3** и получите API key
   в [Google Cloud Credentials](https://console.cloud.google.com/apis/credentials).
2. Ограничьте ключ YouTube Data API v3. Браузерное ограничение HTTP referrer
   не подходит серверным запросам этого приложения.
3. В Настройках сохраните ключ, название и настоящий Google Cloud project ID.
4. Создайте исследование: запросы на языке контента, русский/английский, Shorts/видео/всё.
   Остальные параметры заполнены.
5. Запустите один раз или включите мониторинг. Первый результат — исходная точка;
   измеренный рост появится после повторного замера минимум через 30 минут.

Сохранение ключа не расходует квоту и не проверяет его в YouTube.
Ошибки ключа, API и квоты покажет первый запрос. [Руководство](PRODUCT_GUIDE.md).

## Где данные

- `data/radar.sqlite` — исследования, снимки, настройки, очередь; SQLite WAL.
- `data/local-auth.json` — настройки входа. Не публикуйте этот файл.
- YouTube-ключи — Windows Credential Manager через keyring, привязаны к пути базы.
- API-данные удаляются через 28 дней; заметки и ID избранного сохраняются отдельно.

Копируйте всю папку data при остановленном приложении. Для работающей БД используйте
SQLite backup API: копирование только .sqlite без WAL может потерять данные.
На другом компьютере/пути ключи потребуется ввести заново.

## Другие ОС и диагностика

На macOS/Linux возможен запуск с Python 3.11+, исправленной SQLite и системным keyring,
но окружение keyring зависит от ОС. Для headless Linux используйте
[Docker в серверном режиме](README_SERVER.md): desktop keyring не требуется.

Нужна SQLite **3.51.3+**, либо исправленные **3.44.6 / 3.50.7**.
Проверка: `python -c "import sqlite3; print(sqlite3.sqlite_version)"`.
Номер Python сам по себе не гарантирует подходящую SQLite. Не отключайте проверку.

Переменные окружения: `RADAR_DATA_DIR` (папка данных), `RADAR_PORT` (8877).
Локальный режим слушает только loopback. Для публичного прокси используйте серверный режим.

## Демонстрация

```powershell
.\.venv\Scripts\python.exe -X utf8 -m tests.preview_server --catalog
```

http://127.0.0.1:8879 · `fixture-owner` / `fixture-password-123`.
Временные синтетические данные, без запросов к YouTube.
[Тесты и разработка](CONTRIBUTING.md).
