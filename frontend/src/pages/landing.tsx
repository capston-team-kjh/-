import { Link } from "react-router";
import { BookOpen, BarChart3, Target, Brain } from "lucide-react";
import logo from "../assets/joljak_logo.png";

export function Landing() {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border/40 bg-white/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src={logo} alt="FocusAI" className="h-10 w-auto" />
            <span className="text-xl font-semibold text-foreground">FocusAI</span>
          </div>
          <nav className="flex items-center gap-4">
            <Link
              to="/login"
              className="px-4 py-2 text-foreground hover:text-primary transition-colors"
            >
              로그인
            </Link>
            <Link
              to="/signup"
              className="px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
            >
              시작하기
            </Link>
          </nav>
        </div>
      </header>

      <section className="max-w-7xl mx-auto px-6 py-20 text-center">
        <div className="max-w-3xl mx-auto space-y-6">
          <h1 className="text-5xl font-bold text-foreground leading-tight">
            <span className="text-primary">지능형 분석</span>으로<br />학습 세션을 혁신하세요
          </h1>
          <p className="text-xl text-muted-foreground">
            학습 패턴과 생산성에 대한 상세한 인사이트로<br />학습 여정을 추적하고, 분석하고, 최적화하세요.
          </p>
          <div className="flex items-center justify-center gap-4 pt-4">
            <Link
              to="/signup"
              className="px-8 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors text-lg"
            >
              시작하기
            </Link>
          </div>
        </div>

        <div className="mt-16 rounded-xl border border-border bg-white shadow-lg overflow-hidden">
          <div className="p-8 bg-gradient-to-br from-accent/30 to-white">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <StatCard value="2,847" label="누적 학습 시간" />
              <StatCard value="94%" label="목표 달성률" />
              <StatCard value="156" label="이번 달 세션" />
            </div>
          </div>
        </div>
      </section>

      <section className="bg-accent/20 py-20">
        <div className="max-w-7xl mx-auto px-6">
          <h2 className="text-3xl font-bold text-center mb-12">
            성공을 위한 모든 기능
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
            <FeatureCard
              icon={<BookOpen className="w-8 h-8" />}
              title="세션 기록"
              description="정밀한 타이밍과 자동 분류로 학습 세션을 추적하세요."
            />
            <FeatureCard
              icon={<BarChart3 className="w-8 h-8" />}
              title="시각적 분석"
              description="아름다운 차트와 활동 히트맵으로 진행 상황을 확인하세요."
            />
            <FeatureCard
              icon={<Target className="w-8 h-8" />}
              title="목표 설정"
              description="일일 및 월간 목표를 설정하여 동기부여와 트랙을 유지하세요."
            />
            <FeatureCard
              icon={<Brain className="w-8 h-8" />}
              title="스마트 인사이트"
              description="학습 습관을 최적화하기 위한 맞춤형 추천을 받으세요."
            />
          </div>
        </div>
      </section>

      <section className="max-w-7xl mx-auto px-6 py-20 text-center">
        <div className="max-w-2xl mx-auto space-y-6 bg-primary/5 rounded-2xl p-12 border border-primary/20">
          <h2 className="text-3xl font-bold text-foreground">
            학습을 한 단계 업그레이드할 준비가 되셨나요?
          </h2>
          <p className="text-lg text-muted-foreground">
            이미 학업 목표를 달성하고 있는 수천 명의 학생들과 함께하세요.
          </p>
          <Link
            to="/signup"
            className="inline-block px-8 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors text-lg"
          >
            무료로 시작하기
          </Link>
        </div>
      </section>

      <footer className="border-t border-border py-8">
        <div className="max-w-7xl mx-auto px-6 text-center text-muted-foreground">
          <p>© 2026 FocusAI. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}

function StatCard({ value, label }: { value: string; label: string }) {
  return (
    <div className="bg-white rounded-lg p-6 border border-border/50">
      <div className="text-3xl font-bold text-primary mb-1">{value}</div>
      <div className="text-sm text-muted-foreground">{label}</div>
    </div>
  );
}

function FeatureCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="bg-white rounded-xl p-6 border border-border/50">
      <div className="text-primary mb-4">{icon}</div>
      <h3 className="text-lg font-semibold mb-2">{title}</h3>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  );
}