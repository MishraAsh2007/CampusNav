import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import basicSsl from '@vitejs/plugin-basic-ssl';
import { fileURLToPath } from 'node:url';

const routes = ['/api/data', '/health', '/buildings', '/closures', '/reports', '/notices',
  '/plan', '/navigation', '/indoor', '/external-reports'];

// https://vitejs.dev/config/
// `npm run dev:phone` (mode "https") serves over HTTPS with a self-signed certificate, because phones
// only allow GPS (navigator.geolocation) on secure pages. Normal `npm run dev` is unchanged.
export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === 'https' ? [basicSsl()] : [])],
  resolve: {
    preserveSymlinks: true,
  },
  build: {
    rollupOptions: {input: {
      map: fileURLToPath(new URL('./index.html', import.meta.url)),
      indoorDemo: fileURLToPath(new URL('./indoor.html', import.meta.url)),
    }},
  },
  server: {
    port: 5173,
    host: true,
    proxy: Object.fromEntries(routes.map(path => [
      `^${path}(?:/|$)`, {target: 'http://127.0.0.1:8000', changeOrigin: true},
    ])),
  },
}));
