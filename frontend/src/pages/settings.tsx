import { User, Shield } from "lucide-react";

export function Settings() {

  return (
    <div className="p-8 space-y-8 max-w-4xl mx-auto">
      <div>
        <h1 className="text-3xl font-bold text-foreground mb-1">설정</h1>
        <p className="text-muted-foreground">
          계정 및 환경설정 관리
        </p>
      </div>

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
                defaultValue="홍길동"
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
                defaultValue="hong@example.com"
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
          <button className="w-full md:w-auto px-6 py-3 border border-border rounded-lg hover:bg-accent transition-colors text-left">
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
        <button className="px-6 py-3 border border-border rounded-lg hover:bg-accent transition-colors">
          취소
        </button>
        <button className="px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors">
          변경사항 저장
        </button>
      </div>
    </div>
  );
}