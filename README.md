# GPTHub Hack 2026

Проект объединяет OpenWebUI и GPTHub API в одном стенде. OpenWebUI дает интерфейс чата, а GPTHub API отвечает за бизнес-логику, маршрутизацию моделей и кастомные фичи.

## Что внутри

- `apps/gpthub-api` — основной backend на FastAPI.
- `apps/openwebui` — локальная копия OpenWebUI для доработок.
- `docker-compose.yml` — основной compose для деплоя.
- `docker-compose.override.yml` — локальные порты для разработки.
- `config/` — общие конфиги и дефолты для автонастройки моделей.

## Установка и запуск

1. Скопируйте пример окружения:
```bash
cp .env.example .env
```

2. Настройте `.env`.

Дальше откройте `.env` и проверьте основные значения:

- **Порт для проверки**: если у вас указан `OPENWEBUI_EXTERNAL_PORT=3000`, открывайте `http://localhost:3000`. У вас может быть другой порт, поэтому всегда смотрите значение `OPENWEBUI_EXTERNAL_PORT`.
- **MWS GPT**: для работы основной генерации обязательно заполните `MWS_GPT_API_KEY` и поставьте `MWS_STUB_MODE=false`.
- **Автопилот**: для работы этого функционала обязательно укажите `E2B_API_KEY`. Для тестирования мы предоставили наш ключ в .env.example.
- **Админ OpenWebUI**: логин и пароль берутся из `OPENWEBUI_ADMIN_EMAIL` и `OPENWEBUI_ADMIN_PASSWORD`.

Если меняете `OPENWEBUI_EXTERNAL_PORT`, не забудьте открывать именно `http://localhost:{OPENWEBUI_EXTERNAL_PORT}`.

3. Запустите проект:
```bash
docker compose up -d --build
```

4. Проверьте статус:
```bash
docker compose ps
```

5. Откройте сервисы:
- OpenWebUI: `http://localhost:3000`
- GPTHub API: `http://localhost:8000/api/v1/health`

## Настройка `.env`

Файл `.env` задает поведение всего стенда. Главное здесь — база данных, OpenWebUI и MWS GPT.

### База данных

- `GPTHUB_POSTGRES_*` — база для GPTHub API.
- `OPENWEBUI_POSTGRES_*` — база для OpenWebUI.

### MWS GPT

- `MWS_STUB_MODE=true` — режим заглушек. Удобно для локальной разработки.
- `MWS_STUB_MODE=false` — включение реального проксирования в MWS GPT.
- `MWS_GPT_API_KEY` — ключ для реального API.
- `MWS_DEFAULT_MODEL` — модель по умолчанию для обычных запросов.

### OpenWebUI

- `OPENWEBUI_SECRET_KEY` — секретный ключ приложения.
- `OPENWEBUI_ADMIN_EMAIL` / `OPENWEBUI_ADMIN_PASSWORD` — первый админ.
- `OPENWEBUI_ENABLE_SIGNUP=false` — обычно лучше оставить регистрацию выключенной.

### Связь OpenWebUI и GPTHub

- `OPENWEBUI_GPTHUB_API_URL` — адрес GPTHub API внутри compose.
- `OPENWEBUI_GPTHUB_AUTO_BOOTSTRAP_OPENAI=true` — автоматически подхватывает GPTHub как OpenAI-compatible провайдер.
- `OPENWEBUI_OPENAI_API_BASE_URL` / `OPENWEBUI_OPENAI_API_KEY` — отдельный OpenAI-compatible провайдер, если нужен прямой внешний endpoint.
- `OPENWEBUI_OPENAI_API_TITLE` — имя этого подключения в интерфейсе.

## Что лежит в `config/`

Папка `config/` нужна для дефолтов и преднастроек, которые проект использует при старте.

- `config/auto-model-defaults.json` — стартовые значения для автомодели и мультимодала.
- Здесь задаются базовые модели, например модель для классификации, STT и привязка типов задач к моделям.
- Если меняете этот файл, лучше потом пересобрать контейнеры, чтобы новые значения точно подхватились.

## Коротко о потоке запросов

1. Пользователь пишет сообщение в OpenWebUI.
2. OpenWebUI Backend принимает запрос.
3. GPTHub API выбирает нужную модель и применяет свою бизнес-логику.
4. Запрос уходит либо в MWS GPT, либо в другой OpenAI-compatible провайдер.
5. Ответ возвращается обратно в чат.
