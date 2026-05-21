# Twitch Guess Game MVP

Production deployment guide: see `DEPLOY.md`.

Мини-игра для Twitch с browser overlay для OBS. Работает через чат Twitch и EventSub.

## Возможности

- ответы от зрителей, опционально только от фолловеров;
- команды управления для стримера и модераторов;
- overlay с подсказкой, таймером, ответом и топом игроков;
- отдельный источник вопросов для Dota 2;
- автоставки для Dota 2 и CS2;
- React-кабинет для управления настройками, таймерами, ставками и ботом.

## Установка

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Заполни `.env`.

## Основные переменные

- `APP_PUBLIC_BASE_URL` — публичный адрес приложения;
- `SESSION_SECRET` — длинный случайный секрет для сессий;
- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`
- `TWITCH_REDIRECT_URI`
- `TWITCH_BOT_USER_ACCESS_TOKEN`
- `TWITCH_BOT_USER_REFRESH_TOKEN`
- `TWITCH_BOT_USER_ID`
- `TWITCH_BOT_USER_LOGIN`
- `TWITCH_EVENTSUB_SECRET`

### Вопросы и игра

- `ANSWER_COOLDOWN_SECONDS` — минимальный интервал попыток одного пользователя;
- `QUESTIONS_CATEGORY` — фильтр по категории;
- `QUESTIONS_PATH_MAIN` — основной файл вопросов;
- `QUESTIONS_PATH_DOTA` — файл вопросов Dota 2;
- `USER_QUESTIONS_DIR` — директория пользовательских конфигов.

### Чат-бот Twitch

- `CHATBOT_BADGE_MODE=false` — стабильный режим отправки сообщений через user token;
- `CHATBOT_BADGE_MODE=true` — сначала пробуем App Access Token, при ошибке автоматически откатываемся назад.

Для попадания бота в `Chat Bots` в `Users in Chat` есть отдельный флаг:

- `CHATBOT_CHATTERS_LIST_MODE=false` — чтение чата остаётся на WebSocket EventSub;
- `CHATBOT_CHATTERS_LIST_MODE=true` — дополнительно включается webhook EventSub для `channel.chat.message`.

Для этого нужны:

- публичный `APP_PUBLIC_BASE_URL` с `https://`;
- `TWITCH_EVENTSUB_SECRET`;
- уже рабочий `CHATBOT_BADGE_MODE=true`.

## Запуск

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Автотесты

Smoke-набор проверяет:

- диапазоны и пороги автоставок;
- Dota/CS2 GSI-ветки открытия и закрытия;
- payload для OBS overlay;
- secure session cookie;
- разграничение admin / bot-manager;
- безопасную запись `.env`;
- badge/chat webhook flow и дедуп чата.

Запуск:

```bash
python -m unittest discover -s tests -v
```

Если используешь виртуальное окружение:

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m unittest discover -s tests -v
```

## Debug-маршруты автоставок

Есть admin-only маршруты для проверки без запуска игр:

```bash
curl -X POST http://127.0.0.1:8000/api/app/autobet/debug/dota/open
curl -X POST http://127.0.0.1:8000/api/app/autobet/debug/cs2/open
curl -X POST http://127.0.0.1:8000/api/app/autobet/debug/cs2/close
```

Они используют текущий активный канал из кабинета.

## Frontend

В проекте есть отдельный frontend на `Vite + React + shadcn/ui` в директории `frontend/`.

Локальная разработка:

```bash
cd frontend
npm install
npm run dev
```

Прод-сборка:

```bash
cd frontend
npm install
npm run build
```

После появления `frontend/dist/index.html` backend автоматически начинает отдавать SPA для `/dashboard`, `/stats`, `/settings`, `/commands`, `/giveaways`, `/autobet`, `/timers` и `/admin`.

## Overlay

Открой в браузере:

- `http://127.0.0.1:8000/overlay`

Добавь URL в OBS через Browser Source.

Рекомендуемый размер источника:

- width: `520`
- height: `800`
- background: transparent

Для auto-bet overlay используй отдельный URL из кабинета.

## Команды модераторов

- `!start` — начать раунд
- `!skip` — пропустить раунд
- `!refresh` — перезапустить раунд и сбросить очки
- `!stop` — остановить игру и сбросить очки
- `!pause` — пауза
- `!resume` — продолжить
- `!answer` — показать ответ
- `!top` — написать топ-3 в чат
- `!resetpoints` — сбросить очки
- `!reload` — перечитать активный файл вопросов
- `!setcategory <категория>` — переключить категории
- `!setsource <main|dota>` — переключить источник вопросов
- `!ping` — проверить, что бот жив

## Поведение раундов

- если слово угадано раньше лимита, следующий раунд стартует не раньше минимальной паузы;
- после `!skip` новый раунд начинается сразу;
- если никто не угадал, в overlay показывается правильный ответ, затем начинается следующий раунд;
- при паузе таймер показывает «Пауза».

## Важно

- не коммить `.env`;
- после утечки или публикации секретов обязательно ротируй `TWITCH_CLIENT_SECRET`, `SESSION_SECRET` и токены бота.
