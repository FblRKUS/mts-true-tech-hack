# MTS True Tech Hack - Multi-Agent AI System

Универсальный AI-чат с мультиагентной архитектурой на базе OpenWebUI API.

## 🏗️ Архитектура

Проект реализует паттерн **Supervisor** с LangGraph:

- **Project Manager (Supervisor)** - координирует работу агентов, декомпозирует задачи
- **Worker Agents**:
  - 🎨 **UX/UI Designer** - проектирует интерфейсы
  - 💻 **Frontend Developer** - пишет React код
  - ⚙️ **Backend Developer** - реализует FastAPI сервисы
  - 🐳 **DevOps Engineer** - создает Docker конфигурации
  - ✅ **QA/Tester** - тестирует в E2B sandbox (макс. 3 итерации)

## 🛠️ Tech Stack

- **API**: FastAPI (Python 3.11+)
- **LLM Gateway**: LiteLLM
- **Orchestration**: LangGraph
- **Memory**: 
  - Long-term: Mem0 + Qdrant (RAG)
  - Short-term: PostgresSaver (thread state)
- **Databases**: PostgreSQL, Qdrant
- **Sandbox**: E2B SDK
- **Infrastructure**: Docker, Docker Compose

## 📁 Структура проекта

```
app/
├── __init__.py
├── main.py                  # FastAPI application entry point
├── api/                     # API endpoints
│   ├── __init__.py
│   └── chat.py             # /v1/chat/completions endpoint
├── core/                    # Configuration & database
│   ├── __init__.py
│   ├── config.py           # Pydantic settings
│   └── database.py         # DB manager & PostgresSaver
├── models/                  # Pydantic schemas
│   ├── __init__.py
│   └── schemas.py          # Request/Response models
├── services/                # External integrations
│   ├── __init__.py
│   ├── memory.py           # Mem0 wrapper
│   ├── e2b_runner.py       # E2B sandbox runner
│   └── llm_router.py       # LiteLLM wrapper
└── agents/                  # LangGraph nodes
    ├── __init__.py
    ├── graph.py            # Graph compilation
    ├── supervisor.py       # Project Manager logic
    └── nodes/              # Worker agent implementations
        ├── __init__.py
        ├── designer.py
        ├── frontend_dev.py
        ├── backend_dev.py
        ├── devops.py
        └── qa_tester.py
```

## 🚀 Быстрый старт

### 1. Подготовка окружения

```bash
# Клонировать репозиторий (если применимо)
git clone <repo-url>
cd mts-true-tech-hack

# Создать .env файл из примера
cp .env.example .env
```

### 2. Настроить переменные окружения

Отредактируйте `.env`:

```env
# Обязательные ключи
OPENAI_API_KEY=sk-your-openai-key-here
E2B_API_KEY=your-e2b-api-key-here
LITELLM_MASTER_KEY=sk-your-litellm-key

# Остальные параметры можно оставить по умолчанию
```

### 3. Запустить с Docker Compose

```bash
# Собрать и запустить все сервисы
docker-compose up -d --build

# Проверить логи
docker-compose logs -f app

# Проверить здоровье сервиса
curl http://localhost:8000/health
```

### 4. Использование API

**Эндпоинт**: `POST http://localhost:8000/v1/chat/completions`

**Формат запроса** (OpenAI-совместимый):

```json
{
  "model": "gpt-4",
  "messages": [
    {
      "role": "user",
      "content": "Создай простой веб-калькулятор с React фронтендом и FastAPI бэкендом"
    }
  ],
  "thread_id": "optional-thread-id",
  "user": "user-123"
}
```

**Пример с curl**:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [
      {"role": "user", "content": "Создай TODO-лист приложение"}
    ],
    "user": "hackathon-user"
  }'
```

## 🔄 Workflow агентов

1. **Supervisor** анализирует запрос пользователя
2. Декомпозирует на подзадачи и выбирает агента
3. **Designer** создает UI/UX спецификацию
4. **Frontend Dev** пишет React компоненты
5. **Backend Dev** реализует API и бизнес-логику
6. **DevOps** генерирует Docker конфигурации
7. **QA Tester** запускает код в E2B sandbox и дает фидбек
8. Если тесты не прошли, **Supervisor** маршрутизирует к разработчикам (макс. 3 итерации)
9. **Supervisor** формирует финальный ответ пользователю

## 🧠 Система памяти

- **Long-term (Mem0 + Qdrant)**: контекст из прошлых разговоров, предпочтения пользователя
- **Short-term (PostgresSaver)**: состояние графа LangGraph для конкретного `thread_id`

## 📊 Мониторинг

```bash
# Логи приложения
docker-compose logs -f app

# Проверить БД
docker-compose exec postgres psql -U mts_user -d mts_agentic_db

# Qdrant UI
open http://localhost:6333/dashboard
```

## 🛑 Остановка

```bash
# Остановить сервисы
docker-compose down

# Удалить volumes (БД и Qdrant)
docker-compose down -v
```

## 🔧 Разработка без Docker

```bash
# Установить зависимости
pip install -r requirements.txt

# Запустить PostgreSQL и Qdrant отдельно или обновить DATABASE_URL в .env

# Запустить приложение
python -m uvicorn app.main:app --reload
```

## 📝 Примечания

- **Рекурсия LangGraph**: установлен лимит 50 итераций (`LANGGRAPH_RECURSION_LIMIT`)
- **QA тестирование**: максимум 3 итерации фидбека (`MAX_QA_ITERATIONS`)
- **E2B timeout**: 30 сек для одиночного кода, 60 сек для проектов
- **Structured logging**: JSON формат для удобного парсинга

## 🐛 Troubleshooting

**Проблема**: `psycopg2` не устанавливается
- **Решение**: Используйте `psycopg2-binary` (уже в requirements.txt)

**Проблема**: Qdrant недоступен
- **Решение**: Проверьте `docker-compose logs qdrant`, убедитесь что порт 6333 свободен

**Проблема**: E2B тесты падают с timeout
- **Решение**: Увеличьте `timeout` параметр в `e2b_runner.py` или проверьте E2B API key

## 📚 Дополнительные ресурсы

- [LangGraph Docs](https://langchain-ai.github.io/langgraph/)
- [Mem0 Documentation](https://docs.mem0.ai/)
- [E2B SDK](https://e2b.dev/docs)
- [LiteLLM](https://docs.litellm.ai/)

## 🎯 Roadmap

- [ ] Streaming responses (SSE)
- [ ] Multi-modal support (image/audio processing)
- [ ] Web UI для мониторинга графа
- [ ] Metrics & observability (Prometheus/Grafana)
- [ ] Horizontal scaling с Kubernetes

---

**Версия**: 1.0.0  
**Лицензия**: MIT  
**Команда**: MTS True Tech Hack
