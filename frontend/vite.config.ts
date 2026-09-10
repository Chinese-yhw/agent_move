import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发代理：/api 与 /media 全部转发到后端，前端直接用相对路径
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/media': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
