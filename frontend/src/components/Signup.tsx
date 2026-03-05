import { useState } from 'react';

interface SignupProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings') => void;
}

export function Signup({ onNavigate }: SignupProps) {

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const handleSignupSubmit = async () => {
    // 1. Check for empty fields (New addition!)
    if (!email.trim() || !password.trim()) {
      alert("이메일과 비밀번호를 모두 입력해주세요.");
      return;
    }

    // 2. Check for minimum length (Recommended for your demo)
    if (password.length < 8) {
      alert("비밀번호는 최소 8자 이상이어야 합니다.");
      return;
    }
    
    // 1. Validation check
    if (password !== confirmPassword) {
      alert("비밀번호가 일치하지 않습니다.");
      return;
    }

    try {
      const response = await fetch('/api/v1/users/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password }),
      });

      const data = await response.json();

      if (response.ok) {
        alert("회원가입이 완료되었습니다! 로그인해주세요.");
        onNavigate('login'); // Redirect to login page
      } else {
        alert(data.error || "회원가입에 실패했습니다.");
      }
    } catch (error) {
      console.error("Signup error:", error);
      alert("서버 통신 오류가 발생했습니다.");
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

            <div>
              <label className="block mb-2 text-gray-700">비밀번호 확인</label>
              <input 
                type="password" 
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full p-3 border-2 border-gray-400 bg-white"
                placeholder="••••••••"
              />
            </div>

            <button 
              onClick={handleSignupSubmit}
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
