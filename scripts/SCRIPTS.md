# Сохранённые скрипты Flaunt

Все установочные и служебные скрипты **не трогаются** при редизайне фронтенда. Они живут в бэкенде и отдаются по HTTP.

## PowerShell — установка GSI (Dota 2 + CS2)

| Что | Где в коде |
|-----|------------|
| Полный install (cfg + Dota launch option) | `app/web_site_presence.py` → `_build_gsi_install_script()` |
| Pairing install (авторизация + install) | `app/web_site_presence.py` → `_build_gsi_pairing_install_script()` |

## HTTP-эндпоинты

| Метод | URL | Назначение |
|-------|-----|------------|
| GET | `/install` | Pairing-скрипт PowerShell |
| GET | `/install/gsi/authorize?code=…` | Страница авторизации Twitch для установки |
| GET | `/install/gsi/session/{code}` | Статус сессии установки (JSON) |
| GET | `/install/gsi/{token}.ps1` | Готовый `.ps1` для Win+R |

## GSI webhook (игры → сервер)

| Метод | URL |
|-------|-----|
| POST | `/api/dota/gsi/{token}` |
| POST | `/api/cs2/gsi/{token}` |

## Конфиги в ответе API кабинета

Поля `gsi.install_command`, `gsi.config_text`, `gsi.cs2_config_text` в `/api/app/autobet` — генерируются тем же бэкендом.

## Важно при деплое

- Не удалять и не переименовывать маршруты `/install*` и `/api/*/gsi/*`.
- Редизайн затрагивает только `frontend/` (React SPA).
