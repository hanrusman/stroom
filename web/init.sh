#!/bin/bash
set -e

if [ ! -f "package.json" ]; then
    echo "No package.json found. Initializing Next.js project..."
    npx -y create-next-app@latest . \
        --typescript \
        --tailwind \
        --eslint \
        --app \
        --src-dir \
        --import-alias "@/*" \
        --use-npm \
        --yes
    
    echo "Initialization complete!"
fi

echo "Installing dependencies..."
npm install

echo "Starting Next.js development server..."
exec npm run dev
