import { ColorSchemeProvider } from 'gestalt';
import Nav from './Nav.jsx';
import JobsBoard from './pages/JobsBoard.jsx';

function App() {
  return (
    <ColorSchemeProvider colorScheme="light">
      <Nav currentPage="jobs" />
      <JobsBoard />
    </ColorSchemeProvider>
  );
}

export default App;
