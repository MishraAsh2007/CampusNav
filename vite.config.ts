import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import basicSsl from '@vitejs/plugin-basic-ssl';

// https://vitejs.dev/config/
// `npm run dev:phone` (mode "https") serves over HTTPS with a self-signed certificate, because phones
// only allow GPS (navigator.geolocation) on secure pages. Normal `npm run dev` is unchanged.
export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === 'https' ? [basicSsl()] : [])],
  resolve: {
    preserveSymlinks: true,
  },
  server: {
    port: 5173,
    host: true,
    fs: {
      strict: false,
      allow: ['..'],
    },
    // Proxy to teammate backends if they are running locally!
    proxy: {
      '/api/route': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/api/closures': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/api/buildings': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/api/report': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
}));
