// 麦克风录音:独立于 speech.js 的播放链,互不干扰。
// startRecording() 返回 null 表示无权限/不支持(调用方静默跳过,反馈是增强不阻塞练习)。

/** 开始录音;返回 {stop: () => Promise<Blob|null>} 或 null(不可用)。 */
export async function startRecording() {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    return null; // 拒绝授权 / 无麦克风
  }
  if (typeof MediaRecorder === "undefined") {
    stream.getTracks().forEach((t) => t.stop());
    return null;
  }
  const chunks = [];
  let recorder;
  try {
    recorder = new MediaRecorder(stream);
  } catch {
    stream.getTracks().forEach((t) => t.stop());
    return null;
  }
  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };
  recorder.start(250);
  return {
    stop: () =>
      new Promise((resolve) => {
        recorder.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          const type = recorder.mimeType || "audio/webm";
          if (chunks.length === 0) {
            resolve(null);
            return;
          }
          resolve(new Blob(chunks, { type }));
        };
        try {
          recorder.stop();
        } catch {
          resolve(null);
        }
      }),
  };
}

/** Blob → base64 字符串(不带 data: 前缀)。 */
export function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result);
      resolve(dataUrl.slice(dataUrl.indexOf(",") + 1));
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

/** 录音是否可用(无权限也返回 true,授权后才定)。 */
export function recorderSupported() {
  return typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined";
}
