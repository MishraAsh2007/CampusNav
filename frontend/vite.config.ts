import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
const paths = ['/plan', '/route', '/journey', '/indoor', '/health', '/buildings', '/closures', '/notices', '/reports', '/external-reports', '/official-closures'];
export default defineConfig({plugins: [react()], server: {host: '127.0.0.1', port: 5173,
  proxy: Object.fromEntries(paths.map(path => [path, {target: 'http://127.0.0.1:8000', changeOrigin: true}]))}});
