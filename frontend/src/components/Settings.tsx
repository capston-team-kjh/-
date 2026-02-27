import { Navigation } from './Navigation';
import { useState } from 'react';

interface SettingsProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings') => void;
  onLogout: () => void;
  userId: string | null;
  accessToken: string | null;
}

export function Settings({ onNavigate, onLogout, userId, accessToken}: SettingsProps) {
  const [subView, setSubView] = useState<'menu' | 'profile' | 'password'>('menu');
  const [profileData, setProfileData] = useState<any>(null);
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmNewPw, setConfirmNewPw] = useState('');

  const handleFetchProfile = async () => {
    const response = await fetch('/api/users/me', {
      headers: { 'Authorization': `Bearer ${accessToken}` }
    });
    const data = await response.json();
    setProfileData(data);
    setSubView('profile');
  };

  const handlePasswordUpdate = async () => {
    // 1. Check if any fields are empty or just whitespace
    if (!currentPw.trim() || !newPw.trim()) {
      alert("현재 비밀번호와 새 비밀번호를 모두 입력해주세요.");
      return;
    }

    // 2. Enforce a minimum length (e.g., 8 characters)
    if (newPw.length < 8) {
      alert("새 비밀번호는 최소 8자 이상이어야 합니다.");
      return;
    }

    // 3. Confirm match
    if (newPw !== confirmNewPw) {
      alert("새 비밀번호가 일치하지 않습니다.");
      return;
    }
  
    const response = await fetch('/api/users/me/password', {
      method: 'PATCH', // Matching teammate's spec
      headers: { 
        'Content-Type': 'application/json',
        'Authorization': `Bearer demo-token` 
      },
      body: JSON.stringify({ 
        current_password: currentPw, 
        new_password: newPw 
      })
    });
  
    if (response.ok) {
      alert("비밀번호가 성공적으로 변경되었습니다.");

      // Clear the fields so they aren't there when you come back
      setCurrentPw('');
      setNewPw('');
      setConfirmNewPw('');

      setSubView('menu');
    } else {
      const error = await response.json();
      alert(error.message || "변경 실패");
    }
  };

  return (
    <div className="min-h-screen border-2 border-gray-800">
      <Navigation 
        currentPage="settings" 
        onNavigate={onNavigate}
        onLogout={onLogout}
      />

      {/* Page Title */}
      <div className="border-b-2 border-gray-800 p-6">
        <h1 className="text-center">설정</h1>
      </div>

      {/* Main Content */}
      <main className="p-8">
        <div className="max-w-3xl mx-auto">
          {/* My Info Section */}
          {subView === 'menu' && (
            <>
              <div className="border-2 border-gray-600 p-6 mb-6">
                <h2 className="mb-4 pb-2 border-b border-gray-400">내 정보</h2>
                  <div className="border-2 border-gray-400 p-4">
                    <button 
                      onClick={handleFetchProfile}
                      className="w-full text border-2 border-gray-400 p-4 hover:bg-gray-50 transition colors"
                      >
                      <div className="text-gray-700 mb-2">프로필 정보</div>
                      <div className="text-gray-600 text-sm">이메일, 이름 등 기본 정보</div>
                    </button>
                  </div>
                  <div className="border-2 border-gray-400 p-4">
                    <button
                      onClick={() => setSubView('password')}
                      className="w-full text border-2 border-gray-400 p-4 hover:bg-gray-50 transition colors"
                      >
                      <div className="text-gray-700 mb-2">비밀번호 변경</div>
                      <div className="text-gray-600 text-sm">비밀번호 변경 옵션</div>
                    </button>
                  </div>
              </div>

              {/* Data Management Section */}
              <div className="border-2 border-gray-600 p-6">
                <h2 className="mb-4 pb-2 border-b border-gray-400">데이터 관리</h2>
                <div className="space-y-4">
                  <div className="border-2 border-gray-400 p-4">
                    <div className="text-gray-700 mb-2">학습 기록 삭제</div>
                    <div className="text-gray-600 text-sm">전체 또는 선택 기록 삭제</div>
                  </div>
                  <div className="border-2 border-gray-400 p-4">
                    <div className="text-gray-700 mb-2">기록 보관/내보내기</div>
                    <div className="text-gray-600 text-sm">학습 기록 백업 및 내보내기 (선택)</div>
                  </div>
                </div>
              </div>
            </>
          )}

          {/* VIEW 2: Profile Detail - Show if subView is 'profile' */}
          {subView === 'profile' && (
            <div className="border-2 border-gray-600 p-6">
              <button onClick={() => setSubView('menu')} className="mb-4 px-4 py-2 border-2 border-gray-400 hover:bg-gray-100">
                ← 뒤로가기
              </button>
              <h2 className="mb-4 pb-2 border-b border-gray-400">프로필 상세 정보</h2>
              <div className="space-y-4">
              <div className="flex justify-between border-b pb-2">
                <span className="text-gray-600">이메일</span>
                <span className="text-gray-800 font-medium">{profileData?.email || 'Loading...'}</span>
              </div>
              <div className="flex justify-between border-b pb-2">
                <span className="text-gray-600">사용자 고유 ID</span>
                <span className="text-gray-800 text-xs">{userId}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">계정 생성일</span>
                <span className="text-gray-800">{profileData?.created_at || 'Loading...'}</span>
              </div>
              </div>
            </div>
          )}

          {/* VIEW 3: Password Update - Show if subView is 'password' */}
          {subView === 'password' && (
            <div className="border-2 border-gray-600 p-6">
              <button onClick={() => {
                setSubView('menu');
                setCurrentPw('');
                setNewPw('');
                setConfirmNewPw('');
              }} 
              className="mb-4 px-4 py-2 border-2 border-gray-400 hover:bg-gray-100">
                ← 뒤로가기
              </button>
              <h2 className="mb-4 pb-2 border-b border-gray-400">비밀번호 변경</h2>
              <div className="space-y-4 max-w-md">
                <input 
                  type="password" 
                  placeholder="현재 비밀번호" 
                  value={currentPw}
                  onChange={(e) => setCurrentPw(e.target.value)}
                  className="w-full p-3 border-2 border-gray-400" 
                />
                <input 
                  type="password" 
                  placeholder="새 비밀번호" 
                  value={newPw}
                  onChange={(e) => setNewPw(e.target.value)}
                  className="w-full p-3 border-2 border-gray-400" 
                />
                <input 
                  type="password" 
                  placeholder="새 비밀번호 확인" 
                  value={confirmNewPw}
                  onChange={(e) => setConfirmNewPw(e.target.value)}
                  className="w-full p-3 border-2 border-gray-400" 
                />
                
                <button onClick={(e) => {
                    handlePasswordUpdate();
                  }}
                  className="w-full py-3 border-2 border-gray-800 bg-white hover:bg-gray-100 transition-colors"
                >
                  비밀번호 수정하기
                </button>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}