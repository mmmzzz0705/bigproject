import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端服务层（FastAPI）默认地址：http://127.0.0.1:8000
// 所有 /api 开头的请求都会被代理到该地址，前端只感知同源的 /api
export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1200
  }
})
