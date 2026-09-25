# Этап 4: эксплуатация SaaS и тарифный контур

Работай в существующем AsBoljam по `00_MASTER_COMMERCIAL_VERSION_RU.md`. Этот этап начинается только после устойчивого tenant и real-data boundary.

## Цель

Подготовить безопасную эксплуатацию коммерческого сервиса и минимальный тарифный контур без преждевременного подключения платежей.

## Задачи

1. Опиши deployment topology для API, worker, web, PostgreSQL, reverse proxy и object storage, включая HTTPS, секреты, health/readiness и миграции.
2. Добавь structured logs с correlation/job ID без cookies, токенов, паролей, connection strings и сырых клиентских строк.
3. Определи метрики и alerts: login failures, import errors, job duration/lease, forecast failures, procurement deficits, approval conflicts, database health, backups и export events.
4. Реализуй backup/restore runbook с retention, шифрованием, тестовым восстановлением и owner responsibility. Не обещай RPO/RTO без измерения.
5. Зафиксируй тарифные сущности: plan, tenant subscription, branch limit, user limit, data retention, support tier, pilot period и status. Billing должен ограничивать доступ предсказуемо, но не ломать audit/export.
6. Платёжный провайдер, счета и налоги подключай только после юридического решения владельца. До этого используй manual invoice/pilot status и не храни данные карт.
7. Подготовь onboarding checklist и support playbook: подключение источника, обучение, incident escalation, data export, offboarding и удаление данных по договору.

## Критерии приёмки

- Есть проверяемая схема deployment и rollback без удаления production volumes.
- Backup можно восстановить в отдельную БД, а результат фиксируется артефактом.
- Ошибка одного tenant/job не раскрывает данные другого и не останавливает весь worker.
- Тарифные ограничения проверяются API и видны пользователю с понятным сообщением.
- Нет реализованного хранения платёжных карт и неподтверждённых заявлений о compliance.

## Обязательная проверка

Запусти изменённые deployment/config, backup/restore, health и billing policy tests. Нагрузку, SLA и независимый security audit помечай `NOT TESTED`, если их реально не выполняли.
