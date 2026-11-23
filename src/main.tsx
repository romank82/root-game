// ПЕРВЫМ: полифилл Buffer для @ton/core/@ton/crypto. Без него падает весь
// бандл (Uncaught ReferenceError: Buffer is not defined) и админка пустая.
import './polyfills'
import { StrictMode } from 'react'
import './i18n'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import App from './App.tsx'
import AdminApp from './AdminApp.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/admin" element={<AdminApp />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
