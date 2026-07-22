export async function setupDualCameras(): Promise<{ faceStream: MediaStream; deskStream: MediaStream }> {
  // 1. Get initial permission
  let permissionStream = await navigator.mediaDevices.getUserMedia({ video: true });
  permissionStream.getTracks().forEach((track) => track.stop()); // Stop immediately, just needed permission

  // 2. Find all available cameras
  const devices = await navigator.mediaDevices.enumerateDevices();
  const allCams = devices.filter((d) => d.kind === "videoinput");

  if (allCams.length < 2) {
    throw new Error("카메라가 2개 필요합니다 (얼굴용, 책상용)");
  }

  const faceCamId = allCams[0].deviceId;
  const deskCamId = allCams[1].deviceId;

  console.log("Using Camera 1 (Face):", faceCamId);
  console.log("Using Camera 2 (Desk):", deskCamId);

  // 3. Request specific streams from the chosen cameras
  const [faceStream, deskStream] = await Promise.all([
    navigator.mediaDevices.getUserMedia({
      video: { deviceId: { exact: faceCamId }, width: 640, height: 480 },
    }),
    navigator.mediaDevices.getUserMedia({
      video: { deviceId: { exact: deskCamId }, width: 640, height: 480 },
    }),
  ]);

  return { faceStream, deskStream };
}