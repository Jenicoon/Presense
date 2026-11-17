import { Upload } from "tus-js-client";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export const RECORDING_OPTIONS = { videoBitsPerSecond: 500_000, audioBitsPerSecond: 48_000 };
export const RECORDING_CONSTRAINTS = {
  video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 360 }, frameRate: { ideal: 15, max: 20 } },
  audio: true,
};
export type UploadProgress = { sent: number; total: number };

export async function uploadSessionVideo(path: string, video: Blob, onProgress?: (value: UploadProgress) => void) {
  if (!video.size) throw new Error("녹화 파일이 비어 있어요. 세션 기록은 유지됩니다.");
  const client = getSupabaseBrowserClient();
  if (!client) throw new Error("영상 서버에 연결할 수 없어요.");
  const { data: { session } } = await client.auth.getSession();
  if (!session) throw new Error("로그인이 만료됐어요. 다시 로그인한 뒤 영상 업로드를 이어갈 수 있어요.");
  const base = process.env.NEXT_PUBLIC_SUPABASE_URL!.replace(/\/$/, "");
  // The loopback test server supports the SDK's ordinary upload endpoint.
  if (video.size <= 6 * 1024 * 1024 || new URL(base).hostname === "127.0.0.1" || new URL(base).hostname === "localhost") {
    const { error } = await client.storage.from("session-videos").upload(path, video, {
      contentType: video.type || "video/webm", upsert: true,
    });
    if (error) throw new Error(error.message);
    onProgress?.({ sent: video.size, total: video.size });
    return;
  }
  const storageBase = base.replace(/^(https:\/\/[^.]+)\.supabase\.co$/, "$1.storage.supabase.co");
  await new Promise<void>((resolve, reject) => {
    const upload = new Upload(video, {
      endpoint: storageBase + "/storage/v1/upload/resumable",
      // Set Authorization only in onBeforeRequest. XHR appends repeated headers,
      // producing an invalid combined JWT when it is also set here.
      headers: { apikey: process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!, "x-upsert": "true" },
      metadata: { bucketName: "session-videos", objectName: path, contentType: video.type || "video/webm", cacheControl: "3600" },
      chunkSize: 6 * 1024 * 1024,
      retryDelays: [0, 1000, 3000, 5000],
      uploadDataDuringCreation: true,
      removeFingerprintOnSuccess: true,
      // Separate attempts and users must never resume each other's object.
      fingerprint: async () => `presense:${path}:${video.size}:${video.type}`,
      onProgress: (sent, total) => onProgress?.({ sent, total }),
      onSuccess: () => resolve(),
      onError: error => reject(new Error(error.message)),
      onBeforeRequest: async request => {
        const underlying = request.getUnderlyingObject();
        if (typeof XMLHttpRequest !== "undefined" && underlying instanceof XMLHttpRequest) underlying.timeout = 30_000;
        const { data } = await client.auth.getSession();
        if (!data.session) throw new Error("로그인이 만료됐어요. 다시 로그인한 뒤 업로드를 이어갈 수 있어요.");
        request.setHeader("Authorization", `Bearer ${data.session.access_token}`);
      },
    });
    void upload.findPreviousUploads().then(previous => {
      if (previous[0]) upload.resumeFromPreviousUpload(previous[0]);
      upload.start();
    }).catch(reject);
  });
}
