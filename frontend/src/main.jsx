import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import 'gestalt/dist/gestalt.css'
import { applyTheme } from './theme.js'
import './index.css'
import App from './App.jsx'

applyTheme()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
