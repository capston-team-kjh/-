import { useState } from 'react';
import { Home } from './components/Home';
import { Login } from './components/Login';
import { Signup } from './components/Signup';
import { Dashboard } from './components/Dashboard';
import { Learning } from './components/Learning';
import { ResultList } from './components/ResultList';
import { ResultDetail } from './components/ResultDetail';
import { Settings } from './components/Settings';

type Page = 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings';

export default function App() {
  const [currentPage, setCurrentPage] = useState<Page>('home');
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);

  const navigate = (page: Page) => {
    setCurrentPage(page);
  };

  const handleLogin = () => {
    setIsLoggedIn(true);
    navigate('dashboard');
  };

  const handleLogout = () => {
    setIsLoggedIn(false);
    navigate('home');
  };

  const handleViewResult = (resultId: string) => {
    setSelectedResultId(resultId);
    navigate('result-detail');
  };

  return (
    <div className="min-h-screen bg-white">
      {currentPage === 'home' && <Home onNavigate={navigate} />}
      {currentPage === 'login' && <Login onNavigate={navigate} onLogin={handleLogin} />}
      {currentPage === 'signup' && <Signup onNavigate={navigate} />}
      {currentPage === 'dashboard' && <Dashboard onNavigate={navigate} onLogout={handleLogout} onViewResult={handleViewResult} />}
      {currentPage === 'learning' && <Learning onNavigate={navigate} onLogout={handleLogout} onViewResult={handleViewResult} />}
      {currentPage === 'result-list' && <ResultList onNavigate={navigate} onLogout={handleLogout} onViewResult={handleViewResult} />}
      {currentPage === 'result-detail' && <ResultDetail onNavigate={navigate} onLogout={handleLogout} resultId={selectedResultId} />}
      {currentPage === 'settings' && <Settings onNavigate={navigate} onLogout={handleLogout} />}
    </div>
  );
}