import { useState } from 'react';

interface LoginProps {
  onNavigate: (
    page:
      | 'home'
      | 'login'
      | 'signup'
      | 'dashboard'
      | 'learning'
      | 'result-list'
      | 'result-detail'
      | 'settings'
      | 'history-delete'
  ) => void;
  onLogin: (userData: { user_id: string; access_token: string }) => void;
}

type AnyObj = Record<string, any>;

export function Login({ onNavigate, onLogin }: LoginProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleLoginSubmit = async () => {
    if (!email.trim() || !password.trim()) {
      alert('이메일과 비밀번호를 모두 입력해주세요.');
      return;
    }

    try {
      const response = await fetch('/api/v1/users/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      const data = await response.json().catch(() => ({} as AnyObj));

      if (response.ok) {
        const userId = String(data.user_id ?? data.userId ?? data.user?.user_id ?? '');
        const accessToken = String(
          data.access_token ?? data.accessToken ?? data.token ?? data.access_token_value ?? ''
        );

        // 다른 화면들이 localStorage를 보니까 여기서도 저장해두면 안정적임
        if (userId) localStorage.setItem('userId', userId);
        if (accessToken) localStorage.setItem('accessToken', accessToken);

        onLogin({ user_id: userId, access_token: accessToken });
        onNavigate('dashboard');
      } else {
        alert(data.detail || data.error || '로그인 실패. 정보를 확인해주세요.');
      }
    } catch (error) {
      console.error('Login error:', error);
      alert('서버와 통신 중 오류가 발생했습니다.');
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
                onChange={(e) => setEmail(e.target.value)}
                className="w-full p-3 border-2 border-gray-400 bg-white"
                placeholder="example@email.com"
              />
            </div>

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
              onClick={handleLoginSubmit}
              className="w-full p-3 border-2 border-gray-800 hover:bg-gray-100"
            >
              로그인
            </button>

            <div className="text-center">
              <button onClick={() => onNavigate('signup')} className="text-gray-600 hover:underline">
                회원가입으로 이동
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}