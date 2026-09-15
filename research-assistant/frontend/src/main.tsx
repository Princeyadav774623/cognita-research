import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './AuthContext.tsx'
import { ErrorBoundary } from './ErrorBoundary.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <AuthProvider>
        <App />
      </AuthProvider>
    </ErrorBoundary>
  </StrictMode>,
)

// The real viewport width, excluding the scrollbar. CSS has no unit for this:
// 100vw counts the scrollbar, which is what made full-bleed sections overflow
// the page by the scrollbar's width on every scrollable page.
//
// Measured on a ResizeObserver rather than once at startup: at module load the
// page is still empty and has no scrollbar, so a single reading captures the
// wrong width and is then three pixels too wide forever.
function syncViewportWidth() {
  document.documentElement.style.setProperty(
    "--viewport-width",
    `${document.documentElement.clientWidth}px`
  );
}

syncViewportWidth();
window.addEventListener("resize", syncViewportWidth);
if (typeof ResizeObserver !== "undefined") {
  new ResizeObserver(syncViewportWidth).observe(document.documentElement);
}
