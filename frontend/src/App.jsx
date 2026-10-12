import ThemeProvider from './design/ThemeProvider.jsx';
import Nav from './Nav.jsx';
import JobsBoard from './pages/JobsBoard.jsx';

function App() {
  return (
    <ThemeProvider colorScheme="light">
      <Nav currentPage="jobs" />
      <JobsBoard />
    </ThemeProvider>
  );
}

export default App;
