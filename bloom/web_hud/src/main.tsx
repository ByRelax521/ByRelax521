import { StrictMode, Suspense, lazy, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import App from './App.tsx'
import { getRole } from './lib/camera'
import { token } from './lib/api'
import { TokenGate } from './components/TokenGate'

// Kamera rolündeki cihaz (eski iPhone) Jarvis arayüzünü değil kamera ekranını açar; ayrı parça olarak yüklenir.
const CameraDevice = lazy(() => import('./camera/CameraDevice'))

/** Sunucu anahtar istiyorsa ve bu cihazdaki anahtar yoksa/yanlışsa önce anahtar ekranı */
function Root() {
  const [auth, setAuth] = useState<'?' | 'ok' | 'yok'>('?')
  useEffect(() => {
    fetch('/api/time', { headers: token ? { 'x-jarvis-token': token } : {} })
      .then(r => setAuth(r.status === 401 ? 'yok' : 'ok'))
      .catch(() => setAuth('ok')) // sunucuya ulaşılamıyorsa uygulama kendi hatasını gösterir
  }, [])
  if (auth === '?') return null
  if (auth === 'yok') return <TokenGate wrong={!!token} />
  return getRole() === 'kamera' ? <Suspense fallback={null}><CameraDevice /></Suspense> : <App />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
