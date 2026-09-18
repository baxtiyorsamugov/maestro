# Архитектура Maestro

## 1. Как есть сейчас

```
Telegram ──polling──> bot.py (2687 строк)
                         │  хендлеры + клавиатуры + бизнес-логика + SQL + тексты
                         ├─> database.py (модели, engine, async_session)
                         ├─> scheduler.py (APScheduler: напоминания, follow-up, тарифы)
                         ├─> utils.py (календарь), texts.py (частичная локализация)
                         └─> booking_cache / search_cache / MemoryStorage  ← в оперативной памяти

Браузер ───HTTP────> admin_panel.py (FastAPI + sqladmin) ──> те же модели
                         └─> /dashboard (KPI), / (статус), /health, /admin (CRUD)

launcher.py = admin-панель в потоке + бот в главном потоке (для Windows .exe)
```

Слоёв нет. Хендлер напрямую открывает сессию БД, пишет SQL, форматирует HTML и отправляет
сообщение. Бизнес-правила (свободен ли слот, активна ли подписка, кто имеет право
подтвердить запись) продублированы в нескольких хендлерах и в шедулере.

## 2. Модель данных

```
Barbershop ──1:N──> Stylist ──1:N──> Service ──N:1──> CatalogService
                       │  1:1 (user_id)
                       ├──> User (role=stylist, subscription_until)
                       ├──1:N──> Schedule          (регулярное расписание по дням недели)
                       ├──1:N──> SpecialSchedule   (исключения на конкретную дату)
                       ├──1:N──> Portfolio         (telegram file_id фотографий)
                       └──N:M──> User (через Favorite)

Booking: user_id, stylist_id, service_id, datetime(строка!), status,
         rating, review_text, reminder_day_sent, reminder_hour_sent, follow_up_sent
```

Замечания к модели:
- `Booking.datetime` — строка `"YYYY-MM-DD HH:MM"`, см. `docs/AUDIT.md` B-2;
- индексов нет ни одного;
- `status` и `role` — свободные строки без ограничения значений;
- нет `created_at` / `updated_at`;
- `Stylist.avg_rating` есть, но никогда не пересчитывается (A-3);
- флаги напоминаний живут в `Booking` — это нормально для текущего масштаба,
  при росте стоит вынести в отдельную таблицу `notifications`.

## 3. Ключевые процессы

### Запись клиента
```
поиск (район | имя | ID) → карточка мастера → услуга → календарь (только дни со слотами)
   → слот → Booking(status=pending) → уведомление мастеру с кнопками
   → мастер: approve / decline → уведомление клиенту
   → после визита: complete → запрос оценки → rating
```
Расчёт свободных слотов: `Schedule` дня недели, перекрытый `SpecialSchedule` на эту дату,
минус существующие брони со статусами `pending`/`approved`, с учётом длительности услуги
(`calculate_available_slots`, `slot_overlaps_existing`).

### Подписка мастера
`users.subscription_until` — единственный рубильник. `NULL` = безлимит.
Проверяется в поиске, в карточке, при записи и при входе в меню мастера
(`is_stylist_subscription_active`). Продление — вручную через админку.

### Фоновые задачи (`Asia/Tashkent`)
| Задача | Расписание | Что делает |
|---|---|---|
| `check_reminders` | каждый час, :00 | напоминание за 24 ч и за 1 ч |
| `check_follow_ups` | 10:00 | «пора обновить образ» через 20 дней после визита |
| `check_subscription_expiry` | 10:05 | мастеру: тариф истекает через 7/3/1 день |

## 4. Куда идём

```
app/
├── bot/
│   ├── handlers/
│   │   ├── client/    registration, search, booking, profile, favorites, reviews
│   │   ├── stylist/   bookings, schedule, services, portfolio, stats, subscription
│   │   └── common/    start, language, errors, fallback
│   ├── keyboards/     reply/, inline/, calendar.py
│   ├── middlewares/   db_session, auth, i18n, throttling, logging, errors
│   ├── states/        FSM-группы
│   ├── filters/       IsStylist, IsActiveSubscription, IsBookingOwner
│   └── callbacks/     CallbackData-фабрики
├── core/              config (pydantic-settings), logging, exceptions, constants
├── db/
│   ├── models/        по одному файлу на агрегат
│   ├── repositories/  booking_repo, stylist_repo, user_repo, schedule_repo
│   └── migrations/    Alembic
├── services/          booking, schedule, subscription, rating, notification, search
├── locales/           ru.ftl, uz.ftl
└── admin/             FastAPI + sqladmin, дашборд, аутентификация

tests/   unit/ (services), integration/ (handlers), conftest.py
docs/    эти документы
```

### Правила слоёв
1. **Handler** — только приём апдейта, вызов сервиса, отрисовка ответа. Ни SQL, ни правил.
2. **Service** — бизнес-правила и транзакции. Ничего не знает про aiogram и про `Message`.
3. **Repository** — запросы к БД. Ничего не знает про правила.
4. **Model** — только описание таблицы.

Зависимости идут строго сверху вниз. Сервис не импортирует хендлер, репозиторий не
импортирует сервис.

### Инфраструктура (целевая)
```
nginx (TLS) ──webhook──> bot (aiogram) ──> PostgreSQL
                              └─────────> Redis (FSM + throttling)
            ──────────> admin (FastAPI) ──> PostgreSQL
                         scheduler (отдельный процесс)
```
Docker Compose, Alembic на старте, Sentry, бэкапы по расписанию.

## 5. Порядок миграции

Переход делается по частям, бот всё время остаётся рабочим:

1. Фаза 1 — точечные исправления в текущей структуре (ничего не переносим).
2. Фаза 2 — Alembic и типы данных; структура файлов ещё прежняя.
3. Фаза 3 — выносим **по одному домену за раз**: сначала `client/booking`, затем
   `stylist/schedule`, и так далее. После каждого выноса — прогон сценария вручную.
4. `bot.py` остаётся точкой входа до конца переноса, постепенно превращаясь в `main.py`.

Не делать «большой переезд» одним коммитом: без тестов (Фаза 5) откатывать будет нечем.
