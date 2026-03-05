import { useState } from 'react'; // Add this import

interface LoginProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings' | 'history-delete') => void;
  onLogin: (userData: { user_id: string }) => void;
}

export function Login({ onNavigate, onLogin }: LoginProps) {
  // 1. Create states for the inputs
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  // 2. The function that talks to your Flask server
  const handleLoginSubmit = async () => {
    try {
      const response = await fetch('/api/v1/users/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }), 
      });
  
      const data = await response.json();
  
      if (response.ok) {
        // We only pass what the FastAPI response actually provides
        onLogin({ user_id: data.user_id }); 
        onNavigate('dashboard');
      } else {
        alert(data.detail || '로그인 실패');
      }
    } catch (error) {
      alert('서버 연결 실패');
    }
  };

  return (
    <div className="min-h-screen border-2 border-gray-800 flex flex-col">
      <div className="border-b-2 border-gray-800 p-6">
        <h1 className="text-center">로그인</h1>
      </div>

      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md border-2 border-gray-600 p-8">
          <div className="space-y-6">
            <div>
              <label className="block mb-2 text-gray-700">아이디(이메일)</label>
              <input 
                type="email" 
                value={email}
                onChange={(e) => setEmail(e.target.value)} // Update state on type
                className="w-full p-3 border-2 border-gray-400 bg-white"
                placeholder="example@email.com"
              />
            </div>

            <div>
              <label className="block mb-2 text-gray-700">비밀번호</label>
              <input 
                type="password" 
                value={password}
                onChange={(e) => setPassword(e.target.value)} // Update state on type
                className="w-full p-3 border-2 border-gray-400 bg-white"
                placeholder="••••••••"
              />
            </div>

            <button 
              onClick={handleLoginSubmit} // Trigger the API call
              className="w-full p-3 border-2 border-gray-800 hover:bg-gray-100"
            >
              로그인
            </button>

            <div className="text-center">
              <button 
                onClick={() => onNavigate('signup')}
                className="text-gray-600 hover:underline"
              >
                회원가입으로 이동
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}