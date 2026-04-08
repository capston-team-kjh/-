import { Link, useNavigate } from "react-router";
import { useState } from "react";
import logo from "../assets/joljak_logo.png";

export function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
  e.preventDefault();

  try {
    const response = await fetch("http://13.209.127.3:8000/api/v1/users/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: email,
        password: password,
      }),
    });

    const data = await response.json();

    if (response.ok) {
      localStorage.setItem("name", data.name);
      localStorage.setItem("user_id", data.user_id);
      localStorage.setItem("email", email);
      
      navigate("/app"); 
    } else {
      alert(data.detail || "로그인 실패");
    }
  } catch (error) {
    alert("서버와 연결할 수 없습니다.");
  }
};

  return (
    <div className="min-h-screen bg-gradient-to-br from-accent/30 via-white to-accent/20 flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <Link to="/" className="inline-flex items-center gap-3 mb-2">
            <img src={logo} alt="FocusAI" className="h-12 w-auto" />
            <span className="text-2xl font-semibold text-foreground">FocusAI</span>
          </Link>
          <p className="text-muted-foreground">다시 오신 것을 환영합니다!</p>
        </div>

        <div className="bg-white rounded-2xl shadow-lg border border-border p-8">
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label htmlFor="email" className="block text-sm mb-2 text-foreground">
                이메일 주소
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-4 py-3 bg-input-background rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
                placeholder="you@example.com"
                required
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm mb-2 text-foreground">
                비밀번호
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-3 bg-input-background rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
                placeholder="••••••••"
                required
              />
            </div>

            <div className="flex items-center justify-between text-sm">
              <label className="flex items-center gap-2">
                <input type="checkbox" className="rounded border-border" />
                <span className="text-muted-foreground">로그인 상태 유지</span>
              </label>
              <a href="#" className="text-primary hover:underline">
                비밀번호를 잊으셨나요?
              </a>
            </div>

            <button
              type="submit"
              className="w-full py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
            >
              로그인
            </button>
          </form>

          <div className="mt-6 text-center text-sm">
            <span className="text-muted-foreground">계정이 없으신가요? </span>
            <Link to="/signup" className="text-primary hover:underline">
              회원가입
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}