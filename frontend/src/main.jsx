import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Order matters: gestalt's own tokens first, then the CareerOS tokens that
// redeclare them, then the Gestalt bridge. All three land in <head>, so they
// also carry !important to beat DesignTokensProvider's <body>-level :root
// block; see the header comment in design/tokens.css.
import 'gestalt/dist/gestalt.css'
import './design/tokens.css'
import './design/theme.css'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
