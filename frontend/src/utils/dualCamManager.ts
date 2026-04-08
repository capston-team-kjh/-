export class DualCameraManager {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private video1: HTMLVideoElement;
  private video2: HTMLVideoElement;
  private mediaRecorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];

  constructor() {
    this.canvas = document.createElement("canvas");
    this.canvas.width = 640;   // Matches AI horizontal limit
    this.canvas.height = 960;  // Stacked 480 + 480
    this.ctx = this.canvas.getContext("2d")!;
    this.video1 = document.createElement("video");
    this.video2 = document.createElement("video");
  }

  async start(cam1Id: string, cam2Id: string) {
    // 1. Capture both streams
    const [s1, s2] = await Promise.all([
      navigator.mediaDevices.getUserMedia({ video: { deviceId: cam1Id, width: 640, height: 480 } }),
      navigator.mediaDevices.getUserMedia({ video: { deviceId: cam2Id, width: 640, height: 480 } })
    ]);

    this.video1.srcObject = s1;
    this.video2.srcObject = s2;
    await Promise.all([this.video1.play(), this.video2.play()]);

    // 2. Start drawing the "OBS-style" split-screen
    const render = () => {
      if (this.mediaRecorder?.state === "recording") {
        this.ctx.drawImage(this.video1, 0, 0, 640, 480);     // Top: Face
        this.ctx.drawImage(this.video2, 0, 480, 640, 480);   // Bottom: Desk
        requestAnimationFrame(render);
      }
    };

    // 3. Setup recording at 5 FPS (matching AI sampling_fps)
    const stream = this.canvas.captureStream(5); 
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