# AsBoljam — вариант запуска: один сервер (VPS) с Docker Compose и HTTPS

Конкретный вариант первого коммерческого/пилотного развёртывания. Конфигурация проверена
локально (см. «Что проверено»), но **на реальном сервере ещё не разворачивалась**: для этого
нужны решения и доступы владельца (раздел 9). Локальная проверка не является deployment.

## 1. Схема

```text
Интернет ──443/80──► caddy (TLS, сертификат домена, HSTS) ──► web (Nginx: SPA + /api)
                                                                 └──► api (FastAPI) ──► postgres (volume)
                                                                 worker (очередь в БД, расчёты в дочернем процессе)
```

- Наружу открыты только 80/443 (Caddy). API, web и PostgreSQL доступны только во внутренней сети.
- Файлы: `docker-compose.yml` + `infra/compose.prod.yml`, `infra/Caddyfile`, пример настроек
  `infra/production.env.example`. Миграции применяются API при старте.
- Логи: JSON-события API/worker и безопасный JSON access log Nginx; Caddy access log выключен
  (он записал бы сырые URL). Ротация docker-логов: 10 МБ × 5 файлов на сервис.

## 2. Требования к серверу

- Linux x86_64 (рекомендуется Ubuntu 24.04 LTS), Docker Engine и Compose v2.24+ (нужен `!reset`).
- Ориентир для одного филиала: 2 vCPU, 4 ГБ RAM, 40 ГБ SSD. Обучение HGB занимает CPU на десятки
  секунд; ёмкость под нагрузкой не измерялась.
- Публичный IPv4, DNS-запись `A` домена на этот адрес, входящие 80 и 443.
- Доступ по SSH с ключами; пароли не передавать в чат/репозиторий.

## 3. Установка

```sh
# 1) Скопировать архив и .sha256 на сервер, проверить и распаковать в новую папку
sha256sum -c AsBoljam_Final.zip.sha256
unzip AsBoljam_Final.zip -d /opt/asboljam && cd /opt/asboljam/AsBoljam

# 2) Приватные настройки
cp infra/production.env.example .env && chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # вставить в POSTGRES_PASSWORD
# заполнить ASBOLJAM_SITE_ADDRESS и ALLOWED_ORIGINS доменом; DEMO_PASSWORD оставить пустым

# 3) Запуск
docker compose --env-file .env -f docker-compose.yml -f infra/compose.prod.yml up -d --build
docker compose --env-file .env -f docker-compose.yml -f infra/compose.prod.yml ps   # api/postgres healthy
```

Если используется `-p <имя>`, задавайте его одинаково везде (или `COMPOSE_PROJECT_NAME`), иначе
Compose будет считать стек другим проектом.

## 4. Проверка после запуска

```sh
python3 scripts/verify_tls_deployment.py --site https://<домен> --closed-port 8000 --closed-port 3000
```

Проверяет доверенный сертификат, HSTS, отсутствие `Server`, редирект HTTP→HTTPS, readiness API,
серверный `X-Request-ID` и закрытые внутренние порты. С `--admin-email` и паролем в переменной
окружения дополнительно проверяет отказ чужому Origin, Secure/HttpOnly/SameSite cookie, вход и выход.

## 5. Первая организация и администратор

Demo seed в production запрещён. Оператор создаёт пустую организацию и первого администратора
(сначала preflight, затем `--apply` со скрытым вводом пароля в терминале):

```sh
C="docker compose --env-file .env -f docker-compose.yml -f infra/compose.prod.yml"
$C exec api python scripts/manage_tenant.py bootstrap --organization-id <id> --name "<название>" \
  --timezone Asia/Almaty --admin-email <email> --operator-id <оператор> --reason "<причина>"
$C exec api python scripts/manage_tenant.py bootstrap ... --apply      # интерактивно, нужен TTY
```

Регистрация REAL-источника — только после согласования данных с предприятием:
[REAL_DATA_OPERATIONS_RU](REAL_DATA_OPERATIONS_RU.md), [TENANT_OPERATIONS_RU](TENANT_OPERATIONS_RU.md).

## 6. Резервные копии

```sh
# ежедневно в 02:15 UTC; удаление копий старше 30 дней — только при явной настройке
15 2 * * * cd /opt/asboljam/AsBoljam && BACKUP_RETENTION_DAYS=30 bash scripts/backup_postgres.sh >> /var/log/asboljam-backup.log 2>&1
```

`scripts/backup_postgres.sh`: `pg_dump --format=custom`, проверка `pg_restore --list`, SHA256,
файлы только для владельца, без перезаписи. Копии нужно регулярно выносить за пределы сервера
(способ выбирает владелец) и ежемесячно проводить учение по восстановлению в новую базу
([INSTALL_UPDATE_BACKUP_RU §6](INSTALL_UPDATE_BACKUP_RU.md)).

## 7. Обновление и откат

По [INSTALL_UPDATE_BACKUP_RU §5](INSTALL_UPDATE_BACKUP_RU.md): backup → проверка восстановления →
остановка worker/api → новая версия в новой папке с тем же `.env` → `up -d --build` →
`verify_tls_deployment.py`. Откат — восстановление проверенной копии в новую базу и прежняя
версия приложения. Не выполнять `docker compose down -v`.

## 8. Эксплуатация и безопасность

- Firewall: SSH только с адресов администраторов, 80/443 открыты, PostgreSQL не публикуется.
- Автоматические обновления безопасности ОС; `.env` и `backups/` с правами только владельца.
- Мониторинг: внешний uptime-check `https://<домен>/api/v1/ready` (сервис выбирает владелец),
  место на диске, `docker compose ps` (healthchecks), журнал backup.
- Readiness не проверяет worker: отслеживать, что задания выходят из очереди (история расчётов).
- Не реализовано: HA/реплики, автоматический failover, централизованный сбор логов и алерты.

## 9. Что нужно от владельца

1. Хостинг и расположение сервера. Учётные записи сотрудников (email) — персональные данные;
   требования законодательства РК о хранении персональных данных нужно подтвердить юридически
   (вероятно, сервер в Казахстане).
2. Домен (или поддомен) и доступ к DNS для записи `A`.
3. Кто оператор сервера: создание доступа и вход выполняет владелец; пароли не передаются в чат.
4. Где хранить копии вне сервера и кто проводит ежемесячное восстановление.
5. Данные первой организации: название, часовой пояс, email администратора; решение о пилоте.

## 10. Что проверено (11.10.2026, локально)

Локальный стек `docker-compose.yml + infra/compose.prod.yml` с `ASBOLJAM_ENV=production`,
`ASBOLJAM_SITE_ADDRESS=localhost` (внутренний CA Caddy), PostgreSQL 17.11, образ
`caddy:2.10.2-alpine` (`sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d`):
`verify_tls_deployment.py` — 15/15; demo seed отклонён production-конфигурацией; ротация логов у
всех сервисов; Caddy без access log, в логах нет паролей и сырых URL; `backup_postgres.sh` создаёт
проверяемые копии, неверный параметр хранения отклоняется до создания копии, копия
восстанавливается в новую базу с теми же количествами строк. **Не проверено:** выпуск
публичного сертификата, DNS, реальный сервер, firewall, нагрузка и отказоустойчивость.
Отчёт: [deployment-config-20261011.json](../../artifacts/verification/deployment-config-20261011.json).
