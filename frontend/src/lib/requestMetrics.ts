export type RequestMetricsEntry = {
  method: string;
  url: string;
  at: number;
};

export type RequestMetricsSnapshot = {
  requestCount: number;
  duplicateCount: number;
  duplicates: RequestMetricsEntry[];
  recentRequests: RequestMetricsEntry[];
};

const DUPLICATE_WINDOW_MS = 1000;
const MAX_RECENT = 50;
const MAX_DUPLICATES = 50;

let requestCount = 0;
let duplicateCount = 0;
const recentByKey = new Map<string, number>();
const duplicates: RequestMetricsEntry[] = [];
const recentRequests: RequestMetricsEntry[] = [];

function normalizeUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

function requestMethod(
  input: RequestInfo | URL,
  init?: RequestInit,
): string {
  if (init?.method) return init.method.toUpperCase();
  if (input instanceof Request) return input.method.toUpperCase();
  return "GET";
}

function requestKey(method: string, url: string): string {
  return `${method} ${url}`;
}

function pruneRecentKeys(now: number): void {
  for (const [key, seenAt] of recentByKey) {
    if (now - seenAt > DUPLICATE_WINDOW_MS) {
      recentByKey.delete(key);
    }
  }
}

export function recordRequest(method: string, url: string, at = Date.now()): void {
  requestCount += 1;
  const normalizedMethod = method.toUpperCase();
  const key = requestKey(normalizedMethod, url);
  const previousAt = recentByKey.get(key);
  if (previousAt != null && at - previousAt <= DUPLICATE_WINDOW_MS) {
    duplicateCount += 1;
    if (duplicates.length >= MAX_DUPLICATES) duplicates.shift();
    duplicates.push({ method: normalizedMethod, url, at });
  }
  recentByKey.set(key, at);
  pruneRecentKeys(at);
  if (recentRequests.length >= MAX_RECENT) recentRequests.shift();
  recentRequests.push({ method: normalizedMethod, url, at });
}

export function getRequestMetricsSnapshot(): RequestMetricsSnapshot {
  return {
    requestCount,
    duplicateCount,
    duplicates: [...duplicates],
    recentRequests: [...recentRequests],
  };
}

export function resetRequestMetrics(): void {
  requestCount = 0;
  duplicateCount = 0;
  recentByKey.clear();
  duplicates.length = 0;
  recentRequests.length = 0;
}

export function installRequestMetrics(): void {
  if (typeof window === "undefined" || window.__metrics) return;

  const originalFetch = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    recordRequest(requestMethod(input, init), normalizeUrl(input));
    return originalFetch(input, init);
  };

  window.__metrics = {
    requests: getRequestMetricsSnapshot,
  };
}

declare global {
  interface Window {
    __metrics?: {
      requests: () => RequestMetricsSnapshot;
    };
  }
}

export {};
