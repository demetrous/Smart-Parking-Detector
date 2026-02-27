import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { SpotsProvider } from './state/SpotsProvider.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SpotsProvider>
      <App />
    </SpotsProvider>
  </StrictMode>,
)
