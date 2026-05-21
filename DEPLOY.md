# Deploy Guide

## 1. Copy project

```bash
sudo mkdir -p /opt/twitch_guess_game_mvp
sudo chown -R $USER:$USER /opt/twitch_guess_game_mvp
```

Upload the repository contents into `/opt/twitch_guess_game_mvp`.

## 2. Install Python environment

```bash
cd /opt/twitch_guess_game_mvp
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
mkdir -p data/user_questions
```

## 3. Configure `.env`

Start from `.env.example` and fill at least:

- `APP_PUBLIC_BASE_URL`
- `SESSION_SECRET`
- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`
- `TWITCH_REDIRECT_URI`
- `TWITCH_EVENTSUB_SECRET`
- `TWITCH_BOT_USER_ACCESS_TOKEN`
- `TWITCH_BOT_USER_ID`
- `TWITCH_BOT_USER_LOGIN`
- `CHATBOT_BADGE_MODE`
- `CHATBOT_CHATTERS_LIST_MODE`
- `DB_PATH`
- `QUESTIONS_PATH_MAIN`
- `QUESTIONS_PATH_DOTA`
- `USER_QUESTIONS_DIR`

Recommended production values:

```env
APP_HOST=0.0.0.0
APP_PORT=8000
APP_PUBLIC_BASE_URL=https://example.com
SESSION_SECRET=replace-with-long-random-secret
TWITCH_REDIRECT_URI=https://example.com/auth/twitch/callback
TWITCH_EVENTSUB_SECRET=replace-with-long-random-eventsub-secret
DB_PATH=/opt/twitch_guess_game_mvp/game.db
QUESTIONS_PATH_MAIN=/opt/twitch_guess_game_mvp/data/questions.json
QUESTIONS_PATH_DOTA=/opt/twitch_guess_game_mvp/data/questions_dota2.json
USER_QUESTIONS_DIR=/opt/twitch_guess_game_mvp/data/user_questions
CHATBOT_BADGE_MODE=false
CHATBOT_CHATTERS_LIST_MODE=false
```

## 4. Twitch Developer Console

In your Twitch application settings:

- set the OAuth redirect URL to `https://example.com/auth/twitch/callback`

The value must exactly match `TWITCH_REDIRECT_URI`.

To let the bot appear in `Chat Bots` under `Users in Chat`, keep `CHATBOT_BADGE_MODE=true` and then separately enable `CHATBOT_CHATTERS_LIST_MODE=true`. This second flag starts webhook EventSub for `channel.chat.message` and requires a public `https://` callback based on `APP_PUBLIC_BASE_URL`.

## 5. systemd service

Copy the service template:

```bash
sudo cp deploy/twitch-guess-game.service /etc/systemd/system/twitch-guess-game.service
sudo systemctl daemon-reload
sudo systemctl enable twitch-guess-game
sudo systemctl restart twitch-guess-game
sudo systemctl status twitch-guess-game --no-pager -l
```

## 6. nginx

Copy the nginx template and replace `example.com` with your real domain:

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/twitch-guess-game
sudo ln -s /etc/nginx/sites-available/twitch-guess-game /etc/nginx/sites-enabled/twitch-guess-game
sudo nginx -t
sudo systemctl reload nginx
```

## 7. HTTPS with certbot

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d example.com
```

After that, update `.env` so `APP_PUBLIC_BASE_URL` and `TWITCH_REDIRECT_URI` use `https://`.

## 8. Health check

```bash
curl http://127.0.0.1:8000/healthz
```

Expected response:

```json
{"status":"ok"}
```

## 8.1. Smoke tests

После обновления backend полезно прогонять базовый набор тестов:

```bash
cd /opt/twitch_guess_game_mvp
. .venv/bin/activate
python -m unittest discover -s tests -v
```

Этот набор сейчас проверяет:

- диапазоны автоставок;
- Dota/CS2 runtime-ветки;
- overlay payload;
- secure session cookie;
- admin / bot-manager доступ;
- запись `.env`.

## 8.2. Debug auto-bet routes

Если нужно проверить автоставки без запуска Dota 2 или CS2, есть admin-only debug маршруты:

```bash
curl -X POST http://127.0.0.1:8000/api/app/autobet/debug/dota/open
curl -X POST http://127.0.0.1:8000/api/app/autobet/debug/cs2/open
curl -X POST http://127.0.0.1:8000/api/app/autobet/debug/cs2/close
```

Замечания:

- маршруты используют текущий активный канал;
- `cs2/close` пытается закрыть текущую активную CS2 ставку;
- если нужен конкретный `match_id`, его можно передать JSON payload'ом.

## 9. End-to-end check

1. Open `https://example.com`
2. Log in with Twitch
3. Upload a JSON questions file
4. Copy the personal overlay URL from the dashboard
5. Give the bot moderator rights in the Twitch chat:

```text
/mod your_bot_login
```

6. Open the overlay in OBS or a browser
7. Start a round from chat and verify live updates
