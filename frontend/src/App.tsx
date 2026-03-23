import { useState } from 'react';
import { Home } from './components/Home';
import { Login } from './components/Login';
import { Signup } from './components/Signup';
import { Dashboard } from './components/Dashboard';
import { Learning } from './components/Learning';
import { ResultList } from './components/ResultList';
import { ResultDetail } from './components/ResultDetail';
import { Settings } from './components/Settings';
import { HistoryDelete } from './components/HistoryDelete';

type Page = 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings' | 'history-delete';

export default function App() {
  const [currentPage, setCurrentPage] = useState<Page>(()=> {
    return (localStorage.getItem('currentPage') as Page) || 'home';
  });
  const [userId, setUserId] = useState(()=> {          // To store the UUID
    return localStorage.getItem('userId');   
  });
  const [isLoggedIn, setIsLoggedIn] = useState(()=> {
    return localStorage.getItem('isLoggedIn') === 'true';
  });
  const [accessToken, setAccessToken] = useState(() => {
    return localStorage.getItem('accessToken');
  });

  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);

  const navigate = (page: Page) => {
    localStorage.setItem('currentPage', page);
    setCurrentPage(page);
  };

  const handleLogin = (userData: { user_id: string, access_token: string }) => {
    // Save to LocalStorage
    localStorage.setItem('isLoggedIn', 'true');
    localStorage.setItem('userId', userData.user_id);
    localStorage.setItem('accessToken', userData.access_token);
    localStorage.setItem('currentPage', 'dashboard');
  
    // Update State
    setUserId(userData.user_id);
    setAccessToken(userData.access_token);
    setIsLoggedIn(true);
    setCurrentPage('dashboard');
  };

  const handleLogout = () => {
    // Clear LocalStorage
    localStorage.clear(); 
  
    // Reset State
    setIsLoggedIn(false);
    setUserId(null);
    setAccessToken(null);
    setCurrentPage('home');
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
      {currentPage === 'dashboard' && <Dashboard userId={userId} onNavigate={navigate} onLogout={handleLogout} onViewResult={handleViewResult} />}
      {currentPage === 'learning' && <Learning onNavigate={navigate} onLogout={handleLogout} onViewResult={handleViewResult} />}
      {currentPage === 'result-list' && <ResultList onNavigate={navigate} onLogout={handleLogout} onViewResult={handleViewResult} />}
      {currentPage === 'result-detail' && <ResultDetail onNavigate={navigate} onLogout={handleLogout} resultId={selectedResultId} />}
      {currentPage === 'settings' && <Settings userId={userId} onNavigate={navigate} onLogout={handleLogout} accessToken={accessToken}/>}
      {currentPage === 'history-delete' && <HistoryDelete onNavigate={navigate} onLogout={handleLogout} />}
    </div>
  );
}