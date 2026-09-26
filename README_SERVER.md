# Сервер: Docker, HTTPS и обновления

Один владелец, один процесс и постоянный том SQLite. Мониторы работают, пока запущен
контейнер. Готовый образ первого релиза — **Linux amd64**.
Нужны Docker Engine, Compose v2, домен и HTTPS-прокси или свободные порты 80/443.

## 1. Получить релиз и подготовить секрет

На Linux:

```sh
git clone --branch v0.1.0 https://github.com/Vangardo/content_radar.git
cd content_radar
docker pull ghcr.io/vangardo/content_radar:0.1.0
mkdir -p deploy/secrets
docker run --rm -it --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$PWD/deploy,dst=/opt/radar/deploy" \
  ghcr.io/vangardo/content_radar:0.1.0 python -m app.server_setup
```

Введите логин, **свой домен без https://** и пароль от 12 символов.
Создастся `deploy/secrets/server.json`: хэш пароля и случайный ключ шифрования.
Сам пароль не сохраняется. Файл исключён из Git и Docker build context.
Сохраните защищённую копию файла. Потеря ключа шифрования потребует повторного ввода
YouTube API-ключей. Не генерируйте новый секрет при обычном обновлении.

Альтернатива: запустите `python -m app.server_setup` из исходников в Python-окружении
с установленной `cryptography==50.0.1`, затем соберите образ из исходников, как описано ниже.

## 2. Запустить с автоматическим HTTPS

DNS домена должен указывать на сервер; TCP 80 и 443 должны быть свободны.
Этот вариант запускает собственный Caddy. Для существующего прокси — следующий раздел.

```sh
export RADAR_DOMAIN=radar.example.com  # замените своим доменом из server.json
docker compose -f compose.yaml -f compose.release.yaml -f compose.https.yaml config --quiet
docker compose -f compose.yaml -f compose.release.yaml -f compose.https.yaml pull
docker compose -f compose.yaml -f compose.release.yaml -f compose.https.yaml up -d --no-build
docker compose -f compose.yaml -f compose.release.yaml -f compose.https.yaml ps
```

Откройте HTTPS-адрес своего домена, войдите, добавьте YouTube API key и создайте исследование.
Стандартных серверных паролей нет. Сохраните RADAR_DOMAIN в локальном `.env`
(см. `.env.example`), чтобы следующие команды использовали тот же домен.

## Уже есть HTTPS-прокси

```sh
docker compose -f compose.yaml -f compose.release.yaml pull radar
docker compose -f compose.yaml -f compose.release.yaml up -d --no-build
curl --fail http://127.0.0.1:8877/healthz
```

Порт приложения привязан к loopback хоста. Проксируйте свой домен на
`http://127.0.0.1:8877`, передавая исходный Host и X-Forwarded-Proto: https.
Если прокси в контейнере, его 127.0.0.1 — другой контейнер: подключите Radar
к выделенной общей Docker-сети и используйте имя сервиса. Не открывайте порт всем интерфейсам.

Домен должен присутствовать в hosts файла секрета. `RADAR_TRUSTED_PROXIES=*`
рассчитан на закрытую Docker-сеть и loopback-публикацию; в другой схеме ограничьте
значение адресами доверенных прокси. Secure cookies требуют HTTPS. При CDN шифрование
должно работать также между CDN и origin, без режима Flexible.

## Сборка из исходников

После подготовки секрета:

```sh
docker compose build --pull
docker compose up -d
```

Для этого варианта используйте compose.yaml без compose.release.yaml.
Образ устанавливает закреплённые зависимости и проверяет исправленную SQLite.
Контейнер работает от UID/GID 10001, с read-only root, без Linux capabilities.

## Обновление и резервная копия

1. Прочитайте release notes и остановите Radar, чтобы мониторы не писали в БД.
2. Сохраните весь том radar_data и deploy/secrets/server.json в защищённую копию.
3. Получите тег нового релиза и Compose-файлы. Сохраните собственный .env и секрет.
4. Укажите `RADAR_IMAGE=ghcr.io/vangardo/content_radar:НОВАЯ-ВЕРСИЯ`, выполните
   pull, затем up -d --no-build с теми же Compose-файлами.
5. Проверьте ps, /healthz, вход и историю.

Пример копии остановленного тома за существующим прокси:

```sh
umask 077
mkdir -p backups
docker compose -f compose.yaml -f compose.release.yaml stop radar
docker compose -f compose.yaml -f compose.release.yaml run --rm --no-deps -T radar \
  tar -C /data -czf - . > backups/radar-data.tar.gz
cp deploy/secrets/server.json backups/server.json
docker compose -f compose.yaml -f compose.release.yaml up -d --no-build
```

Проверьте завершение команды и читаемость архива до обновления. При использовании Caddy
добавляйте -f compose.https.yaml к эксплуатационным командам; сохраняйте и его тома.
Копии/экспорты содержат приватные запросы и API-данные: ограничьте доступ и срок хранения.

Не выполняйте `docker compose down -v`: это удалит данные. Не увеличивайте replicas
и Uvicorn workers. Старый тег образа **не откатывает миграции БД**: полный откат
требует согласованных старого образа, копии БД и секрета.
Не запускайте копию мониторов параллельно с основным экземпляром.

## Диагностика

- /healthz должен вернуть HTTP 200 и ok: true; проверяет также worker.
- В UI показываются ошибки операций, квоты и хранилища.
- `docker compose logs --tail=100 radar`: удалите личные данные перед отправкой.
- Перезапуск помечает незавершённые задания прерванными, сохраняет результаты и расписания.
- API-данные очищаются через 28 дней. Избранное не делает их бессрочными.
- Смена пароля: новый password_hash через `app.server_security.password_hash()` и
  интерактивный getpass, encryption_key сохранить; перезапустить контейнер.
  Старые сессии отзываются. Перед ручным редактированием сохраните секрет.

[HTTP API и продукт](PRODUCT_GUIDE.md) · [Безопасность](SECURITY.md)
