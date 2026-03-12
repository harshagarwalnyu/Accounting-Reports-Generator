# Accounting Reports Generator (Production Ready)

A full-stack professional liquidation report generator using **FastAPI**, **Next.js**, and **LaTeX**.

## 🚀 Quick Start (Docker)

The easiest way to deploy the entire stack is using Docker.

### 1. Build & Run Backend
```bash
cd backend
docker build -t reports-backend .
docker run -p 8000:8000 --env-file .env reports-backend
```

### 2. Build & Run Frontend
```bash
cd frontend
npm install
npm run build
npm start
```

## 🛠 Project Structure

- **`backend/`**: Python FastAPI, Pandas, Jinja2, and LaTeX compilation logic.
- **`frontend/`**: Next.js 15, Tailwind CSS, Shadcn UI, and React Query.
- **`.github/workflows/`**: Continuous Integration (CI) for tests and builds.

## ⚙️ Configuration (Environment Variables)

### Backend (`backend/.env`)
- `OPENAI_API_KEY`: (Optional) For AI-enhanced account mapping and narrative generation.
- `ALLOWED_ORIGINS`: (Default: `*`) Comma-separated list of CORS origins.

### Frontend (`frontend/.env.local`)
- `NEXT_PUBLIC_API_URL`: The URL of your deployed backend (e.g., `https://api.yourdomain.com/api`).

## 🧪 Testing

We use **pytest** for backend logic verification.

```bash
cd backend
pytest
```

## 🚢 GitHub Deployment

1. **CI/CD**: This repository includes a GitHub Action (`.github/workflows/ci.yml`) that automatically runs tests and builds the frontend on every push to `main`.
2. **Vercel**: The frontend is optimized for zero-config deployment on Vercel.
3. **Backend**: Can be deployed to any Docker-capable platform (Railway, Render, AWS, DigitalOcean).

## 📄 License

MIT - 2026
