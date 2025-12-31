import { getToken } from "./auth";

const BASE = process.env.NEXT_PUBLIC_API_BASE!;

export async function api(path: string, options: RequestInit = {}) {
  const token = getToken();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as any),
  };

  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    let msg = "Request failed";
    try {
      const data = await res.json();
      msg = data.detail ?? JSON.stringify(data);
    } catch {}
    throw new Error(msg);
  }

  if (res.status === 204) return null;
  return res.json();
}