/** Queue early clicks until metadata is available; do not clamp to unknown duration. */
export function seekRecording(video: HTMLVideoElement | null, ms: number): boolean {
  if (!video || !Number.isFinite(ms) || ms < 0) return false;
  const previous = pending.get(video);
  if (previous) video.removeEventListener("loadedmetadata", previous);
  const seek = () => {
    pending.delete(video);
    const seconds = ms / 1000;
    video.currentTime = Number.isFinite(video.duration) && video.duration > 0 ? Math.min(seconds, video.duration) : seconds;
    void video.play().catch(() => undefined);
  };
  if (video.readyState === 0) {
    pending.set(video, seek);
    video.addEventListener("loadedmetadata", seek, { once: true });
    video.load();
  } else seek();
  video.scrollIntoView({ behavior: "smooth", block: "center" });
  return true;
}
const pending = new WeakMap<HTMLVideoElement, () => void>();
