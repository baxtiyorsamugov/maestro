# Архитектура Maestro

## 1. Как есть сейчас

```
Telegram ──polling──> bot.py (106 строк)   точка входа: сборка и запуск
                         │
                         ├─> loader.py          bot, dp, storage, middleware
                         ├─> handlers/          13 роутеров по доменам
                         │     ├── client/      registration, search, stylist_card,
                         │     │                booking, profile
                         │     ├── stylist/     panel, bookings, schedule, special_dates,
                         │     │                services, portfolio, stats
                         │     └── fallback     ответ на всё нераспознанное (последний)
                         ├─> guards.py          проверки доступа с ответом пользователю
                         ├─> keyboards.py       разметка
                         ├─> presenters.py      тексты
                         ├─> services/          booking, access, rating
                         ├─> database.py        модели, engine, async_session
                         ├─> timeutils.py       зона, границы периодов, форматы
                         └─> scheduler.py       напоминания, follow-up, тарифы

Браузер ───HTTP────> admin_panel.py (FastAPI + sqladmin) ──> те же модели
                         └─> /dashboard (KPI), / (статус), /health, /admin (CRUD)

launcher.py = admin-панель в потоке + бот в главном потоке (для Windows .exe)
```

Что уже сделано: хендлеры отделены от бизнес-логики, расчёт слотов и права доступа
живут в `services/` и покрыты тестами, тексты и клавиатуры вынесены.

Что осталось: хендлеры всё ещё обращаются к `database` напрямую — слоя репозиториев
нет. Локализация по-прежнему размазана между `texts.py` и инлайн-словарями.
`admin_panel.py` (624 строки) не разбирался.

## 2. Модель данных

```
Barbershop ──1:N──> Stylist ──1:N──> Service ──N:1──> CatalogService
                       │  1:1 (user_id)
                       ├──> User (role=stylist, subscription_until)
                       ├──1:N──> Schedule          (регулярное расписание по дням недели)
                       ├──1:N──> SpecialSchedule   (исключения на конкретную дату)
                       ├──1:N──> Portfolio         (telegram file_id фотографий)
                       └──N:M──> User (через Favorite)

Booking: user_id, stylist_id, service_id, starts_at, ends_at, status, price,
         rating, review_text, reminder_day_sent, reminder_hour_sent, follow_up_sent
```

`Booking.price` — цена на момент записи, в целых сумах. Выручка и «Мои записи» берут её,
а не текущую цену услуги: иначе повышение цены переписывало прошлое. У записей, созданных
до миграции без существующей услуги, она NULL — тогда берётся цена услуги
(`services.booking.booking_price`, `COALESCE` в запросах).

Замечания к модели:
- `status` и `role` — свободные строки; для статусов есть константы `BOOKING_*`
  в `database.py`, но ограничения на уровне схемы пока нет;
- нет `created_at` / `updated_at`;
- `Stylist.avg_rating` и `reviews_count` пересчитываются после каждой оценки;
- флаги напоминаний живут в `Booking` — это нормально для текущего масштаба,
  при росте стоит вынести в отдельную таблицу `notifications`.

## 3. Ключевые процессы

### Время

Все моменты времени — наивные datetime в зоне Asia/Tashkent. Единственная точка
работы со временем — `timeutils.py`, там же обоснование, почему не UTC.
Переход на UTC потребуется при выходе за пределы одной часовой зоны, и менять
придётся только этот модуль.

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

Шаг сетки — длительность услуги плюс `stylists.buffer_min` (минуты между клиентами).
`schedules.break_start` / `break_end` вырезают перерыв, после которого сетка начинается
заново от его конца, а не продолжает утреннюю. У `SpecialSchedule` перерыва нет: разовый
день задаётся своими часами.

Отзыв — это `Booking.review_text` рядом с `rating`: одна запись, одна оценка, один текст.
Модерация постфактум — `review_hidden` скрывает отзыв из карточки, не стирая текст
(`/reviews` в админке). Премодерация в сервисе с одним администратором означала бы,
что отзывы не появляются вообще: очередь некому разбирать.

Запись офлайн-клиента — строка `Booking` с `user_id IS NULL` и именем в `guest_name`.
Статус сразу `approved`, поэтому она попадает в `uq_active_booking_slot` и честно занимает
слот. Клиентские выборки ходят через JOIN по `user_id` и такие записи не видят; напоминания
и follow-up фильтруют их явно (`user_id IS NOT NULL`) — отправлять их некуда.

Перенос записи (`reschedule_<id>`) двигает существующую бронь, а не создаёт вторую, и
исключает её из собственной занятости (`exclude_booking_id`). Окно изменений —
`CHANGE_WINDOW_HOURS`; оно закрывает перенос, но не отмену.

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
