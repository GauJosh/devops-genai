# 🚀 DevOps GenAI Assistant

Your lightweight AI sidekick for DevOps questions, automation guidance, and quick infra troubleshooting.

Built with:
- ⚡ FastAPI
- 🤖 OpenAI API
- 🔐 Environment-based config (`.env`)

---

## ✨ What this project does

This service exposes a simple API with two endpoints:

1. **Health check** to confirm the app is running.
2. **Chat endpoint** to send a prompt and get an AI-generated DevOps response.

Perfect for:
- Internal tooling prototypes
- DevOps helper bots
- Learning how to wire FastAPI + OpenAI quickly

---

## 🧠 How it works (super simple)

1. App starts with FastAPI.
2. It loads your API key and model from `.env`.
3. You send a prompt to `/chat`.
4. The app forwards it to OpenAI with a DevOps-focused system instruction.
5. You get back:
	 - `answer`: model response
	 - `usage`: token usage details (when available)

---

## 📁 Project structure

```text
devops-genai/
├── app.py            # FastAPI application
├── requirements.txt  # Python dependencies
└── README.md
```

---

## ⚙️ Quick Start

### 1) Clone the repo

```bash
git clone https://github.com/GauJosh/devops-genai.git
cd devops-genai
```

### 2) Create and activate virtual environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```cmd
python -m venv .venv
.venv\Scripts\activate
```

### 3) Install dependencies

```bash
pip install -r requirements.txt
```

### 4) Create `.env`

```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini
```

> `OPENAI_MODEL` is optional. If not provided, the app uses `gpt-4o-mini`.

### 5) Run the API

```bash
uvicorn app:app --reload
```

Server starts at:
- `http://127.0.0.1:8000`

Interactive docs:
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

---

## 🔌 API Endpoints

### `GET /healthz`

Checks service status.

**Response example:**
```json
{
	"status": "ok",
	"model": "gpt-4o-mini"
}
```

---

### `POST /chat`

Send your DevOps prompt.

**Request body:**
```json
{
	"prompt": "How do I reduce Docker image size for a Python app?"
}
```

**Response example:**
```json
{
	"answer": "Use a slim base image, multi-stage builds, and avoid copying unnecessary files...",
	"usage": {
		"prompt_tokens": 31,
		"completion_tokens": 72,
		"total_tokens": 103
	}
}
```

---

## 🧪 Quick test with cURL

```bash
curl -X POST "http://127.0.0.1:8000/chat" \
	-H "Content-Type: application/json" \
	-d '{"prompt":"Create a CI/CD checklist for a FastAPI app"}'
```

---

## 🛠 Troubleshooting

- **`OPENAI_API_KEY not set in .env`**  
	Add `OPENAI_API_KEY` to your `.env` file.

- **`401` / authentication errors**  
	Verify your key is valid and active.

- **`500` from `/chat`**  
	Check terminal logs for provider/network errors.

- **Dependency issues**  
	Recreate `.venv` and reinstall using `pip install -r requirements.txt`.

---

## 🌱 Next improvements (optional)

- Add conversation history per session
- Add streaming responses
- Add API key auth for your endpoint
- Add Docker + deployment configs

---

If this helped, give the repo a ⭐ and build something awesome.