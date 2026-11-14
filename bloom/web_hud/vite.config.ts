import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// BLOOM: arayüz Python tarafından (ek_web) yerel olarak sunulur; PWA/service worker YOK.
// MediaPipe wasm + modeller (El Kontrolü) dosyaya gömülmez; ek_web bunları isteğe bağlı "el-varliklari" klasöründen sunar.
export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 900 },
  server: { host: true, allowedHosts: ['.e2b.app'] },
})
