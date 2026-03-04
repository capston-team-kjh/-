import { useState } from 'react';

interface LoginProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail') => void;
  onLogin: (userData: { user_id: number, name: string }) => void;
}

export function Login({ onNavigate, onLogin }: LoginProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = async () => {
    if (!email || !password) {
      alert('아이디 또는 비밀번호가 틀렸습니다.');
      return; 
    }

    try {
      const response = await fetch('http://localhost:8000/api/v1/users/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (response.ok) {
        const data = await response.json();
        alert(data.message);
        onLogin({ user_id: data.user_id, name: data.name });
        onNavigate('dashboard');
      } else {
        const error = await response.json();
        alert(error.detail || '로그인 실패');
      }
    } catch (error) {
      alert('서버와 연결 실패했습니다.');
    }
  };

      
  return (
    <div className="min-h-screen border-2 border-gray-800 flex flex-col">
      {/* Page Title */}
      <div className="border-b-2 border-gray-800 p-6">
        <h1 className="text-center">로그인</h1>
      </div>

      {/* Login Form */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md border-2 border-gray-600 p-8">
          <div className="space-y-6">

            {/* 아이디(이메일) */}
            <div>
              <label className="block mb-2 text-gray-700">아이디(이메일)</label>
              <input 
                type="email" 
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full p-3 border-2 border-gray-400 bg-white"
                placeholder="example@email.com"
              />
            </div>

            {/* 비밀번호 */}
            <div>
              <label className="block mb-2 text-gray-700">비밀번호</label>
              <input 
                type="password" 
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full p-3 border-2 border-gray-400 bg-white"
                placeholder="••••••••"
              />
            </div>

            <button 
              onClick={handleSubmit}
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
