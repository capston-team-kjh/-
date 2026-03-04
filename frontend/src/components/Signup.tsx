interface SignupProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail') => void;
}

export function Signup({ onNavigate }: SignupProps) {
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
              <label className="block mb-2 text-gray-700">아이디(이메일)</label>
              <input 
                type="email" 
                className="w-full p-3 border-2 border-gray-400 bg-white"
                placeholder="example@email.com"
              />
            </div>

            <div>
              <label className="block mb-2 text-gray-700">비밀번호</label>
              <input 
                type="password" 
                className="w-full p-3 border-2 border-gray-400 bg-white"
                placeholder="••••••••"
              />
            </div>

            <div>
              <label className="block mb-2 text-gray-700">비밀번호 확인</label>
              <input 
                type="password" 
                className="w-full p-3 border-2 border-gray-400 bg-white"
                placeholder="••••••••"
              />
            </div>

            <button 
              onClick={() => onNavigate('login')}
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
