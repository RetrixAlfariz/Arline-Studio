function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export const browserStorage = {
  get(key: string): string | null {
    try { return storage()?.getItem(key) ?? null; } catch { return null; }
  },
  set(key: string, value: string): void {
    try { storage()?.setItem(key, value); } catch { /* UI persistence is optional. */ }
  },
  remove(key: string): void {
    try { storage()?.removeItem(key); } catch { /* UI persistence is optional. */ }
  },
  clearArline(): void {
    const target = storage();
    if (!target) return;
    try {
      const keys = Array.from({ length: target.length }, (_, index) => target.key(index))
        .filter((key): key is string => Boolean(key?.startsWith("arline:")));
      keys.forEach((key) => target.removeItem(key));
    } catch {
      // A reset must still succeed when browser storage is blocked.
    }
  },
};

export function createClientId(prefix: string): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return `${prefix}-${crypto.randomUUID()}`;
    }
  } catch {
    // Fall through to a non-cryptographic UI correlation id.
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
