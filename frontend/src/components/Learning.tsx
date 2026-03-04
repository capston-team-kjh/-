import { useState } from 'react';
import { Navigation } from './Navigation';

interface LearningProps {
  onNavigate: (page: 'home' | 'login' | 'signup' | 'dashboard' | 'learning' | 'result-list' | 'result-detail' | 'settings') => void;
  onLogout: () => void;
  onViewResult: (resultId: string) => void;
}

type LearningStatus = 'idle' | 'learning' | 'uploading' | 'analyzing' | 'completed' | 'error';

export function Learning({ onNavigate, onLogout, onViewResult }: LearningProps) {
  const [status, setStatus] = useState<LearningStatus>('idle');

  const handleStart = () => {
    setStatus('learning');
  };

  const handleStop = () => {
    setStatus('uploading');
    
    // Simulate upload and analysis
    setTimeout(() => {
      setStatus('analyzing');
      setTimeout(() => {
        setStatus('completed');
      }, 2000);
    }, 2000);
  };

  const handleRetry = () => {
    setStatus('uploading');
    setTimeout(() => {
      setStatus('analyzing');
      setTimeout(() => {
        setStatus('completed');
      }, 2000);
    }, 2000);
  };

  const handleViewResult = () => {
    onViewResult('new-result');
  };

  return (
    <div className="min-h-screen border-2 border-gray-800">
      <Navigation 
        currentPage="learning" 
        onNavigate={onNavigate}
        onLogout={onLogout}
      />

      {/* Page Title */}
      <div className="border-b-2 border-gray-800 p-6">
        <h1 className="text-center">학습하기</h1>
      </div>

      {/* Main Content */}
      <main className="p-8">
        <div className="max-w-2xl mx-auto">
          {/* Control Buttons */}
          <div className="border-2 border-gray-600 p-8 mb-6">
            <h2 className="mb-6 pb-2 border-b border-gray-400">학습 진행 제어</h2>
            <div className="flex gap-4 justify-center">
              <button
                onClick={handleStart}
                disabled={status !== 'idle' && status !== 'completed' && status !== 'error'}
                className={`px-8 py-4 border-2 ${
                  status === 'idle' || status === 'completed' || status === 'error'
                    ? 'border-gray-800 hover:bg-gray-100'
                    : 'border-gray-400 bg-gray-100 text-gray-400 cursor-not-allowed'
                }`}
              >
                학습 시작
              </button>
              <button
                onClick={handleStop}
                disabled={status !== 'learning'}
                className={`px-8 py-4 border-2 ${
                  status === 'learning'
                    ? 'border-gray-800 hover:bg-gray-100'
                    : 'border-gray-400 bg-gray-100 text-gray-400 cursor-not-allowed'
                }`}
              >
                학습 종료
              </button>
            </div>
          </div>

          {/* Status Display */}
          <div className="border-2 border-gray-600 p-8">
            <h2 className="mb-6 pb-2 border-b border-gray-400">상태</h2>
            
            {status === 'idle' && (
              <div className="text-center p-8 border-2 border-gray-400">
                <p className="text-gray-600">학습을 시작하려면 "학습 시작" 버튼을 클릭하세요</p>
              </div>
            )}

            {status === 'learning' && (
              <div className="text-center p-8 border-2 border-gray-600 bg-gray-50">
                <div className="mb-4">
                  <div className="w-16 h-16 border-4 border-gray-800 mx-auto mb-4"></div>
                  <p className="text-gray-800">학습 중...</p>
                </div>
                <p className="text-gray-600 text-sm">집중하여 학습하세요. 완료 후 "학습 종료"를 클릭하세요.</p>
              </div>
            )}

            {status === 'uploading' && (
              <div className="space-y-4">
                <div className="p-4 border-2 border-gray-600 bg-gray-100">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-800"></div>
                    <div>
                      <p className="text-gray-800">업로드 중...</p>
                      <p className="text-gray-600 text-sm">학습 데이터를 업로드하고 있습니다</p>
                    </div>
                  </div>
                </div>
                <div className="p-4 border-2 border-gray-400">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-400"></div>
                    <p className="text-gray-400">분석 대기 중</p>
                  </div>
                </div>
                <div className="p-4 border-2 border-gray-400">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-400"></div>
                    <p className="text-gray-400">완료</p>
                  </div>
                </div>
                <div className="p-4 border-2 border-gray-400">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-400"></div>
                    <p className="text-gray-400">실패(재시도)</p>
                  </div>
                </div>
              </div>
            )}

            {status === 'analyzing' && (
              <div className="space-y-4">
                <div className="p-4 border-2 border-gray-400">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-600 bg-gray-200"></div>
                    <p className="text-gray-600">업로드 완료</p>
                  </div>
                </div>
                <div className="p-4 border-2 border-gray-600 bg-gray-100">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-800"></div>
                    <div>
                      <p className="text-gray-800">분석 중...</p>
                      <p className="text-gray-600 text-sm">AI가 학습 집중도를 분석하고 있습니다</p>
                    </div>
                  </div>
                </div>
                <div className="p-4 border-2 border-gray-400">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-400"></div>
                    <p className="text-gray-400">완료</p>
                  </div>
                </div>
                <div className="p-4 border-2 border-gray-400">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-400"></div>
                    <p className="text-gray-400">실패(재시도)</p>
                  </div>
                </div>
              </div>
            )}

            {status === 'completed' && (
              <div className="space-y-4">
                <div className="p-4 border-2 border-gray-400">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-600 bg-gray-200"></div>
                    <p className="text-gray-600">업로드 완료</p>
                  </div>
                </div>
                <div className="p-4 border-2 border-gray-400">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-600 bg-gray-200"></div>
                    <p className="text-gray-600">분석 완료</p>
                  </div>
                </div>
                <div className="p-4 border-2 border-gray-600 bg-gray-100">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-800 bg-gray-300"></div>
                    <p className="text-gray-800">완료</p>
                  </div>
                </div>
                <div className="p-4 border-2 border-gray-400">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-400"></div>
                    <p className="text-gray-400">실패(재시도)</p>
                  </div>
                </div>
                <div className="text-center pt-4">
                  <button
                    onClick={handleViewResult}
                    className="px-6 py-3 border-2 border-gray-800 hover:bg-gray-100"
                  >
                    결과로 이동
                  </button>
                </div>
              </div>
            )}

            {status === 'error' && (
              <div className="space-y-4">
                <div className="p-4 border-2 border-gray-400">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-600 bg-gray-200"></div>
                    <p className="text-gray-600">업로드 완료</p>
                  </div>
                </div>
                <div className="p-4 border-2 border-gray-400">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-600 bg-gray-200"></div>
                    <p className="text-gray-600">분석 완료</p>
                  </div>
                </div>
                <div className="p-4 border-2 border-gray-400">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-600 bg-gray-200"></div>
                    <p className="text-gray-600">완료</p>
                  </div>
                </div>
                <div className="p-4 border-2 border-gray-800 bg-gray-100">
                  <div className="flex items-center gap-4">
                    <div className="w-8 h-8 border-2 border-gray-800"></div>
                    <div>
                      <p className="text-gray-800">실패(재시도)</p>
                      <p className="text-gray-600 text-sm">업로드/분석 중 오류가 발생했습니다</p>
                    </div>
                  </div>
                </div>
                <div className="text-center pt-4">
                  <button
                    onClick={handleRetry}
                    className="px-6 py-3 border-2 border-gray-800 hover:bg-gray-100"
                  >
                    재시도
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}