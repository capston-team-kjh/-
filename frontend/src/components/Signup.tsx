import { useState } from 'react';

interface SignupProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail') => void;
}

export function Signup({ onNavigate }: SignupProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [password_confirm, setPasswordConfirm] = useState('');
  const [name, setName] = useState('');

  const handleSignup = async () => {
    if (!email || !password || !name) {
      alert("모든 필드를 입력해주세요.");
      return;
    } 
    if (password !== password_confirm) {
      alert("비밀번호가 서로 같지 않습니다.");
      return;
    }

    try {
      const response = await fetch('http://localhost:8000/api/v1/users/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, name }),
      }); 

      if (response.ok) {
        alert("회원가입이 완료되었습니다! 로그인해주세요.");
        onNavigate('login');  
      } else {
        const error = await response.json();
        alert(error.detail || '회원가입 실패');
      }
    } catch (error) {
      alert('서버와 연결 실패했습니다.');
    }
  };

  return (
    <div className="min-h-screen border-2 border-gray-800 flex flex-col">
      {/* Page Title */}
      <div className="border-b-2 border-gray-800 p-6">
        <h1 className="text-center">회원가입</h1>
      </div>

      {/* Signup Form */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md border-2 border-gray-600 p-8">
          <div className="space-y-6">

            {/* 이름 */}
            <div>
              <label className="block mb-2 text-gray-700">이름</label>
              <input 
                type="text" 
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full p-3 border-2 border-gray-400 bg-white"
                placeholder="홍길동"
              />
            </div>

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

            {/* 비밀번호 확인 */}
            <div>
              <label className="block mb-2 text-gray-700">비밀번호 확인</label>
              <input 
                type="password" 
                value={password_confirm}
                onChange={(e) => setPasswordConfirm(e.target.value)}
                className="w-full p-3 border-2 border-gray-400 bg-white"
                placeholder="••••••••"
              />
            </div>

            <button 
              onClick={handleSignup}
              className="w-full p-3 border-2 border-gray-800 hover:bg-gray-100"
            >
              회원가입
            </button>

            <div className="text-center">
              <button 
                onClick={() => onNavigate('login')}
                className="text-gray-600 hover:underline"
              >
                로그인으로 이동
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
