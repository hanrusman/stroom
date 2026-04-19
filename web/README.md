# Stroom Frontend (Fase 8)

This directory will hold the Next.js PWA frontend.

To initialize the project locally on your machine (where `node` and `npm`/`npx` is installed):

1. Switch to this directory: `cd web`
2. Run the Next.js scaffold:
   ```bash
   npx create-next-app@latest . --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm
   ```
3. Once generated, uncomment the build and execution steps in `Dockerfile`.
4. Ensure `NEXT_PUBLIC_API_URL=http://localhost:8100` makes it to your `.env.local` or Next.js config so the frontend can hit the FastAPI backend.
