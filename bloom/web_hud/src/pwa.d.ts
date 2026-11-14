// Kept only for the inactive legacy src/main.tsx entry. The current BLOOM entry
// (src/bloom-main.tsx) does not register a service worker or use the PWA plugin.
declare module 'virtual:pwa-register' {
  export interface RegisterSWOptions {
    immediate?: boolean
    onRegisteredSW?: (url: string, registration?: ServiceWorkerRegistration) => void
  }
  export function registerSW(options?: RegisterSWOptions): (reloadPage?: boolean) => Promise<void>
}
