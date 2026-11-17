import type { AgentReport, ReportRequest } from "@/lib/agent-report";

export type SessionDraft = {
  id: string;
  userId: string;
  title: string;
  recordedAt: string;
  request: ReportRequest;
  video: Blob | null;
  saveVideo: boolean;
  agentReport: AgentReport | null;
  remoteSaved: boolean;
  reportSaved: boolean;
  videoSaved: boolean;
};

async function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open("presense-session-drafts", 1);
    open.onupgradeneeded = () => open.result.createObjectStore("drafts", { keyPath: "id" });
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
    open.onblocked = () => reject(new Error("Draft storage is blocked"));
  });
}
async function access<T>(mode: IDBTransactionMode, operation: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction("drafts", mode);
      const request = operation(transaction.objectStore("drafts"));
      transaction.oncomplete = () => resolve(request.result);
      transaction.onabort = transaction.onerror = () => reject(transaction.error);
    });
  } finally { db.close(); }
}
export async function saveSessionDraft(draft: SessionDraft): Promise<void> {
  await access("readwrite", store => store.put(draft));
}
export function removeSessionDraft(id: string): Promise<undefined> {
  return access("readwrite", store => store.delete(id));
}
export async function loadSessionDraft(userId: string): Promise<SessionDraft | null> {
  const rows = await access<SessionDraft[]>("readonly", store => store.getAll());
  return rows.filter(row => row.userId === userId)
    .sort((a, b) => b.recordedAt.localeCompare(a.recordedAt))[0] ?? null;
}
export const sessionNoteKey = (userId: string, sessionId: string) => `presense-session-note:${userId}:${sessionId}`;
