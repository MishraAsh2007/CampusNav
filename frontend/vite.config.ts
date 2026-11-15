import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import basicSsl from '@vitejs/plugin-basic-ssl';
import { fileURLToPath } from 'node:url';

const routes = ['/api/data', '/api/route', '/health', '/openapi.json', '/buildings', '/closures', '/reports', '/notices',
  '/plan', '/journey', '/plan-wayfinding', '/navigation', '/indoor', '/external-reports'];

// https://vitejs.dev/config/
// Phone mode uses a local HTTPS proxy, never an old deployed API or sample maps.
// basicSsl's certificate is untrusted by default; HTTPS alone does not guarantee
// that a phone will grant GPS. The phone must trust the certificate for that test.
export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === 'https' ? [basicSsl()] : [])],
  define: mode === 'https' ? {
    'import.meta.env.VITE_CAMPUSNAV_INTEGRATED': JSON.stringify('1'),
    'import.meta.env.VITE_CAMPUSNAV_DEMO': JSON.stringify('0'),
  } : undefined,
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
    strictPort: true,
    host: true,
    fs: {
      deny: ['.env', '.env.*', '*.{crt,pem,key}', '**/.git/**', '**/data/private/**'],
    },
    proxy: Object.fromEntries(routes.map(path => [
      `^${path}(?:/|$)`, {target: 'http://127.0.0.1:8000', changeOrigin: true},
    ])),
  },
}));
