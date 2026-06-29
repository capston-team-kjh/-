// src/utils/DualCameraManager.ts
export class DualCameraManager {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private video1: HTMLVideoElement; // Left Feed (Face)
  private video2: HTMLVideoElement; // Right Feed (Desk)
  private mediaRecorder: MediaRecorder | null = null;
  private onChunkReadyCallback: ((blob: Blob, isFinal: boolean) => void) | null = null;
  
  private activeStream: MediaStream | null = null;

  private isProcessingFinalChunk: boolean = false;

  constructor() {
    this.canvas = document.createElement("canvas");
    this.canvas.width = 1280; 
    this.canvas.height = 480; 
    this.ctx = this.canvas.getContext("2d")!;
    this.video1 = document.createElement("video");
    this.video2 = document.createElement("video");
  }

  private startRenderingLoop() {
    const render = () => {
      // Keep rendering as long as the webcam feeds are active, even during recorder handoffs
      if (this.video1.srcObject || this.video2.srcObject) {
        this.ctx.drawImage(this.video1, 0, 0, 640, 480);
        this.ctx.drawImage(this.video2, 640, 0, 640, 480);
        requestAnimationFrame(render);
      }
    };
    render();
  }

  async start(cam1Id: string, cam2Id: string, onChunkReady: (blob: Blob) => void) {
    this.onChunkReadyCallback = onChunkReady;
    
    // 1. Initialize hardware links
    const [s1, s2] = await Promise.all([
      navigator.mediaDevices.getUserMedia({ video: { deviceId: { exact: cam1Id }, width: 640, height: 480 } }),
      navigator.mediaDevices.getUserMedia({ video: { deviceId: { exact: cam2Id }, width: 640, height: 480 } })
    ]);

    this.video1.srcObject = s1;
    this.video2.srcObject = s2;
    await Promise.all([this.video1.play(), this.video2.play()]);

    this.startRenderingLoop();

    this.activeStream = this.canvas.captureStream(10);

    this.mediaRecorder = new MediaRecorder(this.activeStream, { mimeType: "video/webm" });
    this.setupRecorderListeners();
    this.mediaRecorder.start();
  }

  private setupRecorderListeners() {
    if (!this.mediaRecorder) return;

    this.mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0 && this.onChunkReadyCallback) {
        const chunkBlob = new Blob([e.data], { type: "video/webm" });
        
        // Pass the current state of our final flag to study-session.tsx
        this.onChunkReadyCallback(chunkBlob, this.isProcessingFinalChunk);
        
        // Reset the flag immediately after firing the callback so standard ticker chunks stay false
        this.isProcessingFinalChunk = false;
      }
    };
  }

  async requestSlice(isFinal: boolean = false) {
    if (this.mediaRecorder && this.mediaRecorder.state === "recording" && this.activeStream) {
      
      this.isProcessingFinalChunk = isFinal;
      
      this.mediaRecorder.onstop = () => {
        if (this.activeStream) {
          this.mediaRecorder = new MediaRecorder(this.activeStream, { mimeType: "video/webm" });
          this.setupRecorderListeners();
          this.mediaRecorder.start();
        }
      };

      this.mediaRecorder.stop();
    }
  }

  stop(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.mediaRecorder) {
        reject(new Error("녹화 중이 아닙니다."));
        return;
      }

      this.mediaRecorder.onstop = () => {
        this.cleanupStreams();
        this.mediaRecorder = null;
        this.activeStream = null;
        this.onChunkReadyCallback = null;
        resolve();
      };

      this.mediaRecorder.onerror = () => {
        this.cleanupStreams();
        this.mediaRecorder = null;
        this.activeStream = null;
        reject(new Error("녹화 종료 중 오류가 발생했습니다."));
      };

      this.mediaRecorder.stop();
    });
  }

  private cleanupStreams() {
    [this.video1.srcObject, this.video2.srcObject].forEach((stream) => {
      if (stream instanceof MediaStream) {
        stream.getTracks().forEach((track) => track.stop());
      }
    });
    this.video1.srcObject = null;
    this.video2.srcObject = null;
  }
}
  