# MTS True Tech Hack - Multi-Agent AI System 🤖

**OpenAI-совместимый мультиагентный AI с паттерном Supervisor**

## 🎯 Главная фича

Сложный мультиагентный граф (LangGraph) для задач разработки:
- **Project Manager** (Supervisor) координирует 5 worker агентов
- Автоматическая декомпозиция задач и маршрутизация
- QA с тестированием в E2B sandbox (до 3 итераций)
- Долгосрочная память (Mem0 + RAG) + thread persistence (PostgresSaver)

## 🚀 Быстрый старт

```bash
# 1. Настроить .env
cp .env.example .env
# Добавить OPENAI_API_KEY и E2B_API_KEY

# 2. Запустить
docker-compose up -d --build

# 3. Использовать
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4","messages":[{"role":"user","content":"Создай TODO приложение"}]}'
```

## 📊 Архитектура

```
Supervisor (Project Manager)
    ├─> Designer (UI/UX)
    ├─> Frontend Dev (React)
    ├─> Backend Dev (FastAPI)
    ├─> DevOps (Docker)
    └─> QA Tester (E2B)
```

## 📚 Документация

См. **[README_SETUP.md](./README_SETUP.md)** для детальных инструкций.

## 🛠️ Stack

FastAPI • LangGraph • LiteLLM • Mem0 • PostgreSQL • Qdrant • E2B • Docker

