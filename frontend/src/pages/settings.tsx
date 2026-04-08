import { useState } from "react";
import { User, Shield, ChevronLeft } from "lucide-react";
import {useNavigate } from "react-router";

export function Settings() {
  const navigate = useNavigate();
  const userId = localStorage.getItem("user_id");

  // View state: 'main' or 'password'
  const [view, setView] = useState<'main' | 'password'>('main');

  // Form states
  const [profile, setProfile] = useState({
    name: localStorage.getItem("name") || "",
    email: localStorage.getItem("email") || "", 
  });

  const [passwords, setPasswords] = useState({
    current: "",
    new: "",
    confirm: "",
  });

  // --- 1. Handle Bulk Profile Save ---
  const handleSaveAll = async () => {
    if (!userId) return;
    try {
      const response = await fetch(`http://localhost:8000/api/v1/users/${userId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          name: profile.name, 
          email: profile.email }),
      });

      if (response.ok) {
        localStorage.setItem("name", profile.name);
        localStorage.setItem("email", profile.email);
        alert("모든 변경사항이 저장되었습니다.");
      } else {
        alert("저장에 실패했습니다.");
      }
    } catch (error) {
      console.error("Save failed:", error);
    }
  };

  // --- 2. Handle Password Subview Save ---
  const handleUpdatePassword = async () => {
    if (!passwords.current || !passwords.new) {
      alert("모든 필드를 입력해주세요.");
      return;
    }
    if (passwords.new !== passwords.confirm) {
      alert("새 비밀번호 확인이 일치하지 않습니다.");
      return;
    }

    try {
      const response = await fetch(`http://localhost:8000/api/v1/users/${userId}/password`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: passwords.current,
          new_password: passwords.new
        }),
      });

      if (response.ok) {
        alert("비밀번호가 변경되었습니다.");
        setView('main');
      } else {
        const errorData = await response.json();
        alert(errorData.detail || "오류가 발생했습니다.");
      }
    } catch (error) {
      console.error("Password change failed:", error);
    }
  };

  if (view === 'password') {
    return (
      <div className="p-8 max-w-2xl mx-auto space-y-6">
        <button onClick={() => setView('main')} className="flex items-center gap-2 text-muted-foreground hover:text-foreground">
          <ChevronLeft className="w-4 h-4" /> 뒤로 가기
        </button>
        <h2 className="text-2xl font-bold">비밀번호 변경</h2>
        <div className="space-y-4 bg-white p-6 rounded-2xl border border-border">
          <input 
            type="password" 
            placeholder="현재 비밀번호" 
            className="w-full px-4 py-3 border border-border rounded-lg"
            onChange={(e) => setPasswords({...passwords, current: e.target.value})}
          />
          <input 
            type="password" 
            placeholder="새 비밀번호" 
            className="w-full px-4 py-3 border border-border rounded-lg"
            onChange={(e) => setPasswords({...passwords, new: e.target.value})}
          />
          <input 
            type="password" 
            placeholder="새 비밀번호 확인" 
            className="w-full px-4 py-3 border border-border rounded-lg"
            onChange={(e) => setPasswords({...passwords, confirm: e.target.value})}
          />
          <button onClick={handleUpdatePassword} className="w-full py-3 bg-primary text-primary-foreground rounded-lg">
            비밀번호 업데이트
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-8 max-w-4xl mx-auto">
      <div>
        <h1 className="text-3xl font-bold text-foreground mb-1">설정</h1>
        <p className="text-muted-foreground">
          계정 및 환경설정 관리
        </p>
      </div>

      {/* Profile Section */}
      <section className="bg-white rounded-2xl border border-border p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-accent rounded-lg text-primary">
            <User className="w-5 h-5" />
          </div>
          <h2 className="text-xl font-semibold">프로필</h2>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label htmlFor="name" className="block text-sm mb-2">
                이름
              </label>
              <input
                id="name"
                type="text"
                value={profile.name}
                onChange={(e) => setProfile({ ...profile, name: e.target.value })}
                className="w-full px-4 py-3 bg-input-background rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>
            <div>
              <label htmlFor="email" className="block text-sm mb-2">
                이메일 주소
              </label>
              <input
                id="email"
                type="email"
                value={profile.email}
                onChange={(e) => setProfile({ ...profile, email: e.target.value })}
                className="w-full px-4 py-3 bg-input-background rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>
          </div>
        </div>
      </section>

      <section className="bg-white rounded-2xl border border-border p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-accent rounded-lg text-primary">
            <Shield className="w-5 h-5" />
          </div>
          <h2 className="text-xl font-semibold">개인정보 및 보안</h2>
        </div>

        <div className="space-y-4">
          <button onClick={()=>setView('password')} className="w-full md:w-auto px-6 py-3 border border-border rounded-lg hover:bg-accent transition-colors text-left">
            비밀번호 변경
          </button>
          <button className="w-full md:w-auto px-6 py-3 border border-border rounded-lg hover:bg-accent transition-colors text-left">
            내 데이터 다운로드
          </button>
          <button className="w-full md:w-auto px-6 py-3 border border-destructive text-destructive rounded-lg hover:bg-destructive/10 transition-colors text-left">
            계정 삭제
          </button>
        </div>
      </section>

      <div className="flex items-center justify-end gap-4 pt-4">
        <button onClick={()=>navigate('/app')} className="px-6 py-3 border border-border rounded-lg hover:bg-accent transition-colors">
          취소
        </button>
        <button onClick={handleSaveAll} className="px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors">
          변경사항 저장
        </button>
      </div>
    </div>
  );
}