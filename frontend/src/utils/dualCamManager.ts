// src/utils/DualCameraManager.ts
export class DualCameraManager {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private video1: HTMLVideoElement; // Will be Left (Face)
  private video2: HTMLVideoElement; // Will be Right (Desk)
  private mediaRecorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];

  constructor() {
    this.canvas = document.createElement("canvas");
    // Change: 640*2 for width, 480 for height
    this.canvas.width = 1280; 
    this.canvas.height = 480; 
    this.ctx = this.canvas.getContext("2d")!;
    this.video1 = document.createElement("video");
    this.video2 = document.createElement("video");
  }

  async start(cam1Id: string, cam2Id: string) {
    const [s1, s2] = await Promise.all([
      navigator.mediaDevices.getUserMedia({ video: { deviceId: { exact: cam1Id }, width: 640, height: 480 } }),
      navigator.mediaDevices.getUserMedia({ video: { deviceId: { exact: cam2Id }, width: 640, height: 480 } })
    ]);

    this.video1.srcObject = s1;
    this.video2.srcObject = s2;
    await Promise.all([this.video1.play(), this.video2.play()]);

    const render = () => {
      if (this.mediaRecorder?.state === "recording") {
        // Draw Left Feed (Face) at (0, 0)
        this.ctx.drawImage(this.video1, 0, 0, 640, 480);
        // Draw Right Feed (Desk) at (640, 0)
        this.ctx.drawImage(this.video2, 640, 0, 640, 480);
        requestAnimationFrame(render);
      }
    };

    const stream = this.canvas.captureStream(10); // Recording at 10 FPS
    this.mediaRecorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
    this.chunks = [];
    this.mediaRecorder.ondataavailable = (e) => this.chunks.push(e.data);
    
    this.mediaRecorder.start();
    render();
  }

  stop(): Promise<Blob> {
    return new Promise((resolve) => {
      if (this.mediaRecorder) {
        this.mediaRecorder.onstop = () => {
          const blob = new Blob(this.chunks, { type: 'video/webm' });
          // Turn off camera LEDs
          [this.video1, this.video2].forEach(v => {
            (v.srcObject as MediaStream)?.getTracks().forEach(t => t.stop());
          });
          resolve(blob);
        };
        this.mediaRecorder.stop();
      }
    });
  }
}