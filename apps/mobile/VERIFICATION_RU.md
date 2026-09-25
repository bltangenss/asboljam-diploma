# Проверки мобильного клиента

Дата: 25.09.2026. Код находится в `apps/mobile`; он использует тот же FastAPI API.

| Проверка | Фактический результат |
|---|---|
| `npm.cmd run typecheck` | PASS после установки Expo SDK 55 и после обновления вложенной uuid |
| `npm.cmd test` | 13/13 PASS; последняя длительность Node-тестов 455.844 ms |
| Генерация идентификатора проектом `xcode` | PASS: 24 шестнадцатеричных символа с uuid 11.1.1 |
| `npm.cmd install --offline=false --no-fund` после override | Завершено, встроенный npm audit: 0 vulnerabilities |
| `npm.cmd run export:android` | PASS: Metro/Hermes JS bundle, 588 modules, 1.8 MB, 20.831 s; no APK |
| Android debug APK x86 | PASS: `scripts/build_android_debug.ps1 -Architecture x86`, Gradle `:app:assembleDebug` за 4m04s; APK 60911179 bytes, SHA256 `73a0e4c3a56fe7d2c95ea830771f8c4b4f9dc820502a4953f404d4af220e82b2` |
| Android debug APK arm64-v8a | PASS: `scripts/build_android_debug.ps1 -Architecture arm64-v8a`, Gradle `:app:assembleDebug` за 4m54s; APK 59830847 bytes, SHA256 `fd9e925e090e05e2285351c02e86564bc2aa5b23bde47887af27b51e85f0f82d` |
| APK integrity/signature | PASS for both: ZIP CRC, ABI matches requested architecture, AndroidManifest, 8 dex files; `apksigner verify --verbose --print-certs` PASS по APK Signature Scheme v2, debug certificate |
| Android эмулятор / телефон | NOT TESTED: `adb devices` не показал подключённых устройств |
| iOS development build / симулятор / устройство | NOT TESTED |
| Release APK/IPA и Store release | Не создавались и не публиковались |

13 тестов проверяют хранение только refresh token, привязку токена к API, объединение refresh, сохранение idempotency key и версии при 401, отсутствие повторов 403/409, очистку при logout/revocation и пять случаев конкурентного чтения/записи/обновления сессии. Используется имитация HTTP и SecureStore; это не проверка шифрования ОС.

npm audit сначала показал девять moderate записей по цепочке Expo → xcode → uuid 7. Установлен узкий override `xcode.uuid=11.1.1`. Код xcode использует `uuid.v4()`, его реальный вызов проверен после обновления; Expo/React Native не понижались. Основание исправления: https://github.com/advisories/GHSA-w5hq-g745-h8pq .

Локальные debug APK созданы: для телефона обычно использовать `releases/AsBoljam_Debug_arm64-v8a.apk`, для x86-эмулятора — `releases/AsBoljam_Debug_x86.apk`. Это development builds, а не Store/release APK; для реальной проверки нужны устройство/эмулятор, API/Metro сценарий и release-сборка при необходимости. Для следующих проверок использовать команды и checklist из README_RU.md.
