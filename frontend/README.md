# ITAM frontend

React + TypeScript (Vite). See the repository root [README.md](../README.md) for the
full local development workflow via Docker Compose.

```bash
pnpm install
pnpm run dev        # http://localhost:5173, proxies /api to localhost:8000
pnpm run lint        # oxlint
pnpm run typecheck   # tsc -b --noEmit
pnpm run test        # vitest
pnpm run build       # production build
```
