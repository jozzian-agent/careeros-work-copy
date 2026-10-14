import { Route, Routes } from 'react-router-dom';
import ThemeProvider from './design/ThemeProvider.jsx';
import Nav from './Nav.jsx';
import SearchCriteria from './pages/SearchCriteria.jsx';
import JobsBoard from './pages/JobsBoard.jsx';
import JobDetail from './pages/JobDetail.jsx';
import ExperiencesList from './pages/ExperiencesList.jsx';
import ExperienceDetail from './pages/ExperienceDetail.jsx';
import CompaniesList from './pages/CompaniesList.jsx';
import CompanyDetail from './pages/CompanyDetail.jsx';
import Taxonomy from './pages/Taxonomy.jsx';

// JOZ-280: the SPA now owns the detail-page URLs too (server.py mounts the
// same built index.html at each of these paths once CAREEROS_REACT_UI is
// on), so client-side routing picks the page from here on. currentPage is
// per-route, not a fixed prop, so Nav highlights the right tab on every page.
function Page({ currentPage, children }) {
  return (
    <>
      <Nav currentPage={currentPage} />
      {children}
    </>
  );
}

function App() {
  return (
    <ThemeProvider colorScheme="light">
      <Routes>
        <Route path="/" element={<Page currentPage="search"><SearchCriteria /></Page>} />
        <Route path="/jobs" element={<Page currentPage="jobs"><JobsBoard /></Page>} />
        <Route path="/jobs/:id" element={<Page currentPage="jobs"><JobDetail /></Page>} />
        <Route path="/experiences" element={<Page currentPage="experiences"><ExperiencesList /></Page>} />
        <Route path="/experiences/:id" element={<Page currentPage="experiences"><ExperienceDetail /></Page>} />
        <Route path="/companies" element={<Page currentPage="companies"><CompaniesList /></Page>} />
        <Route path="/companies/:id" element={<Page currentPage="companies"><CompanyDetail /></Page>} />
        <Route path="/taxonomy" element={<Page currentPage="taxonomy"><Taxonomy /></Page>} />
      </Routes>
    </ThemeProvider>
  );
}

export default App;
