# Frontend Instructions

This frontend is a Vite + React + TypeScript app.

Follow the repository root `AGENTS.md` first. Frontend-specific conventions:

- Keep route pages thin; put complex product logic in `frontend/src/features/<domain>/`.
- Use `@/` imports for paths under `frontend/src`.
- Use `PascalCase` for components and `useX` for hooks.
- Prefer existing shared components and API helpers before adding new abstractions.
- Add focused Vitest coverage for non-trivial UI state, task streaming, and API behavior.
- Run `npm run lint`, `npm run build`, or targeted tests when relevant.

See `../docs/DEVELOPMENT.md` and `README.md` for the current frontend workflow.
