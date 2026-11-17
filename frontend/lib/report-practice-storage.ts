import type { LiveInferenceFrame } from "@/lib/live-signal";
export type PracticePreference = "original" | "retry" | "same";
export type SavedReportPractice = { recording: Blob; preference: PracticePreference | null; strategyId?: string; planKey?: string; durationMs?: number; measurement?: LiveInferenceFrame; conditionsConfirmed?: boolean };

async function access<T>(
  mode: IDBTransactionMode,
  request: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const open = indexedDB.open("presense-report-practice", 1);
    open.onupgradeneeded = () => open.result.createObjectStore("takes");
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  });
  try {
    return await new Promise<T>((resolve, reject) => {
      const transaction = db.transaction("takes", mode);
      const operation = request(transaction.objectStore("takes"));
      transaction.oncomplete = () => resolve(operation.result);
      transaction.onabort = transaction.onerror = () => reject(transaction.error);
    });
  } finally {
    db.close();
  }
}

export function loadReportPractice(key: string) {
  return access<SavedReportPractice | undefined>("readonly", store => store.get(key));
}

export async function saveReportPractice(key: string, attempt: SavedReportPractice) {
  await access("readwrite", store => store.put(attempt, key));
}
