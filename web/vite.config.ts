import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig, loadEnv} from 'vite';

export default defineConfig(({mode}) => {
  const env = loadEnv(mode, '.', '');
  return {
    plugins: [react(), tailwindcss()],
    define: {
      'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY),
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modifyâfile watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== "true",
      // Comma-separated hostnames the dev server accepts. Add your own public
      // hostname via VITE_ALLOWED_HOSTS=foo.example.com,bar.example.com.
      allowedHosts: [
        'localhost',
        ...((env.VITE_ALLOWED_HOSTS || '').split(',').map(h => h.trim()).filter(Boolean)),
      ],
      proxy: { "/api": { target: "http://127.0.0.1:8100", changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") } },
    },
  };
});
