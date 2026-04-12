export class DualCameraManager {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private video1: HTMLVideoElement;
  private video2: HTMLVideoElement;
  private mediaRecorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];

  constructor() {
    this.canvas = document.createElement("canvas");
    // 320x240 영상 2개를 좌우로 합쳐서 640x240 캔버스 사용
    this.canvas.width = 320;
    this.canvas.height = 120;
    this.ctx = this.canvas.getContext("2d")!;
    this.video1 = document.createElement("video");
    this.video2 = document.createElement("video");
  }

  private cleanupStreams() {
    [this.video1, this.video2].forEach((video) => {
      (video.srcObject as MediaStream | null)?.getTracks().forEach((track) =>
        track.stop()
      );
      video.srcObject = null;
    });
  }

  async start(cam1Id: string, cam2Id: string) {
    if (this.mediaRecorder && this.mediaRecorder.state === "recording") {
      throw new Error("이미 녹화 중입니다.");
    }

    let s1: MediaStream | null = null;
    let s2: MediaStream | null = null;

    try {
      console.log("Opening cam2 first:", cam2Id);
      s2 = await navigator.mediaDevices.getUserMedia({
        video: {
          deviceId: { exact: cam2Id },
          width: { ideal: 160 },
          height: { ideal: 120 },
          frameRate: { ideal: 5, max: 10 },
        },
        audio: false,
      });
      console.log("cam2 opened");

      await new Promise((resolve) => setTimeout(resolve, 2500));

      console.log("Opening cam1 second:", cam1Id);
      s1 = await navigator.mediaDevices.getUserMedia({
        video: {
          deviceId: { exact: cam1Id },
          width: { ideal: 160 },
          height: { ideal: 120 },
          frameRate: { ideal: 5, max: 10 },
        },
        audio: false,
      });
      console.log("cam1 opened");

      this.video1.srcObject = s1;
      this.video2.srcObject = s2;
      this.video1.muted = true;
      this.video2.muted = true;
      this.video1.playsInline = true;
      this.video2.playsInline = true;
      this.video1.autoplay = true;
      this.video2.autoplay = true;

      await this.video1.play();
      await this.video2.play();

      const render = () => {
        if (this.mediaRecorder?.state === "recording") {
          this.ctx.drawImage(this.video1, 0, 0, 160, 120);
          this.ctx.drawImage(this.video2, 160, 0, 160, 120);
          requestAnimationFrame(render);
        }
      };

      const stream = this.canvas.captureStream(10);

      const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp8")
        ? "video/webm;codecs=vp8"
        : "video/webm";

      this.mediaRecorder = new MediaRecorder(stream, { mimeType });
      this.chunks = [];

      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          this.chunks.push(e.data);
        }
      };

      this.mediaRecorder.start();
      render();
    } catch (error) {
      s1?.getTracks().forEach((t) => t.stop());
      s2?.getTracks().forEach((t) => t.stop());
      this.cleanupStreams();
      throw error;
    }
  }

  stop(): Promise<Blob> {
    return new Promise((resolve, reject) => {
      if (!this.mediaRecorder) {
        reject(new Error("녹화 중이 아닙니다."));
        return;
      }

      this.mediaRecorder.onstop = () => {
        const blob = new Blob(this.chunks, { type: "video/webm" });
        this.cleanupStreams();
        this.mediaRecorder = null;
        resolve(blob);
      };

      this.mediaRecorder.onerror = () => {
        this.cleanupStreams();
        this.mediaRecorder = null;
        reject(new Error("녹화 종료 중 오류가 발생했습니다."));
      };

      this.mediaRecorder.stop();
    });
  }
}