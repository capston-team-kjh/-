type ChunkReadyCallback = (
  blob: Blob,
  isFinal: boolean,
  recordedDurationMs: number,
) => void | Promise<void>;

export class DualCameraManager {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private video1: HTMLVideoElement;
  private video2: HTMLVideoElement;
  private mediaRecorder: MediaRecorder | null = null;
  private onChunkReadyCallback: ChunkReadyCallback | null = null;
  private activeStream: MediaStream | null = null;
  private isProcessingFinalChunk = false;
  private recorderStartedAtMs = 0;
  private currentChunkDurationMs = 0;
  private currentChunkUpload: Promise<void> | null = null;
  private activeSlicePromise: Promise<void> | null = null;
  private pendingUploads = new Set<Promise<void>>();
  private uploadErrors: unknown[] = [];

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
      if (this.video1.srcObject || this.video2.srcObject) {
        this.ctx.drawImage(this.video1, 0, 0, 640, 480);
        this.ctx.drawImage(this.video2, 640, 0, 640, 480);
        requestAnimationFrame(render);
      }
    };
    render();
  }

  private createAndStartRecorder() {
    if (!this.activeStream) {
      throw new Error("녹화 스트림이 준비되지 않았습니다.");
    }

    const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp8")
      ? "video/webm;codecs=vp8"
      : "video/webm";
    const recorder = new MediaRecorder(this.activeStream, { mimeType });
    this.mediaRecorder = recorder;
    this.setupRecorderListeners(recorder);
    this.recorderStartedAtMs = performance.now();
    recorder.start();
  }

  async start(
    cam1Id: string,
    cam2Id: string,
    onChunkReady: ChunkReadyCallback,
  ) {
    this.onChunkReadyCallback = onChunkReady;
    this.pendingUploads.clear();
    this.uploadErrors = [];

    const [s1, s2] = await Promise.all([
      navigator.mediaDevices.getUserMedia({
        video: { deviceId: { exact: cam1Id }, width: 640, height: 480 },
      }),
      navigator.mediaDevices.getUserMedia({
        video: { deviceId: { exact: cam2Id }, width: 640, height: 480 },
      }),
    ]);

    this.video1.srcObject = s1;
    this.video2.srcObject = s2;
    await Promise.all([this.video1.play(), this.video2.play()]);

    this.startRenderingLoop();
    this.activeStream = this.canvas.captureStream(10);
    this.createAndStartRecorder();
  }

  private setupRecorderListeners(recorder: MediaRecorder) {
    recorder.ondataavailable = (event) => {
      if (!event.data || event.data.size <= 0 || !this.onChunkReadyCallback) {
        return;
      }

      const isFinal = this.isProcessingFinalChunk;
      const durationMs = this.currentChunkDurationMs;
      const chunkBlob = new Blob([event.data], { type: recorder.mimeType });
      const uploadPromise = Promise.resolve(
        this.onChunkReadyCallback(chunkBlob, isFinal, durationMs),
      );

      this.currentChunkUpload = uploadPromise;
      this.pendingUploads.add(uploadPromise);
      void uploadPromise.then(
        () => this.pendingUploads.delete(uploadPromise),
        (error) => {
          this.pendingUploads.delete(uploadPromise);
          this.uploadErrors.push(error);
        },
      );
      this.isProcessingFinalChunk = false;
    };
  }

  requestSlice(isFinal = false): Promise<void> {
    if (this.activeSlicePromise) {
      return this.activeSlicePromise;
    }
    if (!this.mediaRecorder || this.mediaRecorder.state !== "recording") {
      return Promise.reject(new Error("녹화 중인 영상이 없습니다."));
    }

    const recorder = this.mediaRecorder;
    this.isProcessingFinalChunk = isFinal;
    this.currentChunkDurationMs = Math.max(1, performance.now() - this.recorderStartedAtMs);
    this.currentChunkUpload = null;

    const operation = new Promise<void>((resolve, reject) => {
      recorder.onerror = () => reject(new Error("영상 청크 생성에 실패했습니다."));
      recorder.onstop = () => {
        if (!isFinal && this.activeStream) {
          try {
            this.createAndStartRecorder();
          } catch (error) {
            reject(error);
            return;
          }
        }

        const upload = this.currentChunkUpload;
        if (!upload) {
          reject(new Error("생성된 영상 청크가 비어 있습니다."));
          return;
        }
        upload.then(resolve, reject);
      };
      recorder.stop();
    });

    const trackedOperation = operation.finally(() => {
      if (this.activeSlicePromise === trackedOperation) {
        this.activeSlicePromise = null;
      }
    });
    this.activeSlicePromise = trackedOperation;
    return trackedOperation;
  }

  async stop(): Promise<void> {
    try {
      if (this.activeSlicePromise) {
        await this.activeSlicePromise;
      }
      if (this.mediaRecorder?.state === "recording") {
        await this.requestSlice(true);
      }
      await Promise.all([...this.pendingUploads]);
      if (this.uploadErrors.length > 0) {
        throw this.uploadErrors[0];
      }
    } finally {
      this.cleanupStreams();
      this.mediaRecorder = null;
      this.activeStream = null;
      this.onChunkReadyCallback = null;
      this.activeSlicePromise = null;
    }
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
