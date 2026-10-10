import { ColorSchemeProvider } from 'gestalt';
import JobsBoard from './pages/JobsBoard.jsx';

function App() {
  return (
    <ColorSchemeProvider colorScheme="light">
      <JobsBoard />
    </ColorSchemeProvider>
  );
}

export default App;
