# Проверки мобильного клиента

Дата: 24.09.2026. Код находится в `apps/mobile`; он использует тот же FastAPI API.

| Проверка | Фактический результат |
|---|---|
| `npm.cmd run typecheck` | PASS после установки Expo SDK 55 и после обновления вложенной uuid |
| `npm.cmd test` | 13/13 PASS; последняя длительность Node-тестов 286 ms |
| Генерация идентификатора проектом `xcode` | PASS: 24 шестнадцатеричных символа с uuid 11.1.1 |
| `npm.cmd install --offline=false --no-fund` после override | Завершено, встроенный npm audit: 0 vulnerabilities |
| `npm.cmd run export:android` | PASS: Metro/Hermes JS bundle, 588 modules, 1.8 MB, 61.139 s; no APK |
| Android development build / эмулятор / телефон | NOT TESTED |
| iOS development build / симулятор / устройство | NOT TESTED |
| APK/IPA и Store release | Не создавались и не публиковались |

13 тестов проверяют хранение только refresh token, привязку токена к API, объединение refresh, сохранение idempotency key и версии при 401, отсутствие повторов 403/409, очистку при logout/revocation и пять случаев конкурентного чтения/записи/обновления сессии. Используется имитация HTTP и SecureStore; это не проверка шифрования ОС.

npm audit сначала показал девять moderate записей по цепочке Expo → xcode → uuid 7. Установлен узкий override `xcode.uuid=11.1.1`. Код xcode использует `uuid.v4()`, его реальный вызов проверен после обновления; Expo/React Native не понижались. Основание исправления: https://github.com/advisories/GHSA-w5hq-g745-h8pq .

Нельзя на основании этих результатов утверждать, что native сборки или поведение ОС уже проверены. Для следующих проверок использовать команды и checklist из README_RU.md.
