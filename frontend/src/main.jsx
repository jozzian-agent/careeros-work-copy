import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { IntlProvider } from 'react-intl'
import { BrowserRouter } from 'react-router-dom'
// Order matters: gestalt's own tokens first, then the CareerOS tokens that
// redeclare them, then the Gestalt bridge. All three land in <head>, so they
// also carry !important to beat DesignTokensProvider's <body>-level :root
// block; see the header comment in design/tokens.css.
import 'gestalt/dist/gestalt.css'
import './design/tokens.css'
import './design/theme.css'
import './index.css'
import App from './App.jsx'
// The catalog is imported, not fetched: every string the app renders is
// needed by the first paint, so a runtime fetch would buy a flash of
// untranslated interface and a second failure mode in exchange for
// nothing. Vite inlines the JSON into the bundle.
import messages from './i18n/en.json'

// English is the only locale today, so `locale` and `defaultLocale` are the
// same and react-intl's missing-message fallback never fires in production.
// It still reports a missing id to the console, which is what the i18n
// catalog spec and scripts/check_i18n.py both watch for.
const LOCALE = 'en'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <IntlProvider locale={LOCALE} defaultLocale={LOCALE} messages={messages}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </IntlProvider>
  </StrictMode>,
)
