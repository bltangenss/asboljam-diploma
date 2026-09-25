# Пример mapping profile для POS в Казахстане

Это только шаблон сопоставления названий колонок. Он не доказывает совместимость с конкретным POS и не содержит реальной выгрузки. Реальный mapping получает версию, hash и отдельное согласование владельца данных.

## Продажи

| Canonical field | Частое имя в POS-экспорте | Правило |
|---|---|---|
| `date` | `business_date` / `date` | бизнес-дата, не timestamp |
| `branch_id` | `location_code` / `store_code` | стабильный ID филиала |
| `meal_id` | `product_code` / `menu_item_id` | ID блюда, не название |
| `units_sold` | `sold_portions` / `quantity` | целые наблюдаемые порции |
| `available_portions` | `available_portions` | обязательный факт доступности |
| `stockout_flag` | `was_stockout` | 0/1 из источника |
| `is_open` | `location_open` | 0/1 из календаря POS |
| `promo` | `promotion_active` | 0/1, если источник это хранит |
| `price_kzt` | `price_kzt` / `gross_price` | KZT без молчаливой конвертации |
| `data_origin` | `source_origin` | должна совпасть с декларацией |

## Складские партии

| Canonical field | Частое имя в POS/ERP-экспорте | Правило |
|---|---|---|
| `branch_id` | `location_code` / `store_code` | ID филиала |
| `ingredient_id` | `ingredient_code` / `sku` | ID ингредиента |
| `lot_id` | `batch_code` / `lot` | партия или согласованный surrogate |
| `snapshot_date` | `snapshot_date` / `as_of_date` | точный срез |
| `expiry_date` | `expiry_date` / `best_before` | дата годности |
| `on_hand_qty` | `quantity` / `balance` | Decimal без округления до целого |
| `unit` | `unit` | только согласованные `kg` или `L` |
| `data_origin` | `source_origin` | `REAL` или `SYNTHETIC` |

## Политика mapping

- Каждое canonical поле сопоставляется фактической колонке; константы и догадки запрещены.
- Неизвестная колонка не удаляется молча: dry-run отклоняет файл.
- Если источник не содержит доступные порции, stockout или складской остаток, это фиксируется как отсутствие факта. Продажи не используются для их восстановления.
- CSV адаптера имеет `mapping_version=1`, явные `declared_data_origin`, `declared_currency=KZT` и `declared_sales_unit=portion`.
- Проверка выполняется командой `python scripts/adapt_pos_csv.py --source <private-file> --mapping <private-mapping>`. Вывод dry-run не содержит исходных значений и не пишет в БД.
