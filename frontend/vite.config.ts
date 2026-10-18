import {defineConfig} from 'vite';

export default defineConfig({
  cacheDir: process.env.VITE_CACHE_DIR,
  server: {
    host: '127.0.0.1', port: 5176, strictPort: true,
    proxy: {'/api': {target: process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000', changeOrigin: false}},
  },
});
