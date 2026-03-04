import { Navigation } from './Navigation';

interface ResultDetailProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings') => void;
  onLogout: () => void;
  resultId: string | null;
}

export function ResultDetail({ onNavigate, onLogout, resultId }: ResultDetailProps) {
  return (
    <div className="min-h-screen border-2 border-gray-800">
      <Navigation 
        currentPage="result-detail" 
        onNavigate={onNavigate}
        onLogout={onLogout}
      />

      {/* Page Title */}
      <div className="border-b-2 border-gray-800 p-6">
        <h1 className="text-center">결과 상세</h1>
      </div>

      {/* Main Content */}
      <main className="p-8">
        <div className="max-w-5xl mx-auto space-y-6">
          {/* Summary Metrics */}
          <div className="border-2 border-gray-600 p-6">
            <h2 className="mb-4 pb-2 border-b border-gray-400">요약 지표</h2>
            <div className="grid grid-cols-4 gap-4">
              <div className="border-2 border-gray-400 p-4">
                <div className="text-gray-600 text-sm mb-2">총 학습시간</div>
                <div className="text-gray-800">2h 15m</div>
              </div>
              <div className="border-2 border-gray-400 p-4">
                <div className="text-gray-600 text-sm mb-2">집중 비율</div>
                <div className="text-gray-800">85%</div>
              </div>
              <div className="border-2 border-gray-400 p-4">
                <div className="text-gray-600 text-sm mb-2">집중 시간</div>
                <div className="text-gray-800">1h 55m</div>
              </div>
              <div className="border-2 border-gray-400 p-4">
                <div className="text-gray-600 text-sm mb-2">비집중 시간</div>
                <div className="text-gray-800">20m</div>
              </div>
            </div>
          </div>

          {/* Focus Graph */}
          <div className="border-2 border-gray-600 p-6">
            <h2 className="mb-4 pb-2 border-b border-gray-400">집중도 그래프 (타임라인)</h2>
            <div className="border-2 border-gray-400 p-8 bg-gray-50">
              {/* Y-axis label */}
              <div className="flex gap-4">
                <div className="flex flex-col justify-between text-gray-600 text-sm" style={{ height: '240px' }}>
                  <div>100%</div>
                  <div>75%</div>
                  <div>50%</div>
                  <div>25%</div>
                  <div>0%</div>
                </div>
                
                {/* Graph area */}
                <div className="flex-1 border-2 border-gray-600 relative" style={{ height: '240px' }}>
                  {/* Grid lines */}
                  <div className="absolute inset-0">
                    <div className="h-1/4 border-b border-gray-300"></div>
                    <div className="h-1/4 border-b border-gray-300"></div>
                    <div className="h-1/4 border-b border-gray-300"></div>
                    <div className="h-1/4 border-b border-gray-300"></div>
                  </div>
                  
                  {/* Mock line graph representation */}
                  <div className="absolute inset-0 flex items-end px-4 pb-4">
                    <div className="flex-1 flex items-end justify-around">
                      <div className="w-2 bg-gray-800" style={{ height: '70%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '85%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '65%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '90%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '80%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '75%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '95%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '88%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '82%' }}></div>
                      <div className="w-2 bg-gray-800" style={{ height: '78%' }}></div>
                    </div>
                  </div>
                </div>
              </div>
              
              {/* X-axis label */}
              <div className="ml-12 mt-2 flex justify-between text-gray-600 text-sm">
                <div>14:30</div>
                <div>15:00</div>
                <div>15:30</div>
                <div>16:00</div>
                <div>16:45</div>
              </div>
            </div>
          </div>

          {/* Behavior Summary */}
          <div className="border-2 border-gray-600 p-6">
            <h2 className="mb-4 pb-2 border-b border-gray-400">습관 행동 요약</h2>
            <div className="space-y-3">
              <div className="border-2 border-gray-400 p-4">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-gray-700">자세 변화 횟수</span>
                  <span className="text-gray-800">12회</span>
                </div>
                <div className="text-gray-600 text-sm">평균보다 적음 (양호)</div>
              </div>
              <div className="border-2 border-gray-400 p-4">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-gray-700">시선 이탈 횟수</span>
                  <span className="text-gray-800">8회</span>
                </div>
                <div className="text-gray-600 text-sm">평균 수준</div>
              </div>
              <div className="border-2 border-gray-400 p-4">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-gray-700">휴식 시간</span>
                  <span className="text-gray-800">15분</span>
                </div>
                <div className="text-gray-600 text-sm">적절한 휴식을 취했습니다</div>
              </div>
            </div>
          </div>

          {/* Back Button */}
          <div className="text-center pt-4">
            <button
              onClick={() => onNavigate('result-list')}
              className="px-6 py-3 border-2 border-gray-600 hover:bg-gray-100"
            >
              목록으로 돌아가기
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
