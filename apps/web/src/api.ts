import { QueryClient } from '@tanstack/react-query';
import type { Auth } from './types';
import { localParts } from './dates';
import { recordedRequest } from './recorded';
export const demoOnly = import.meta.env.VITE_DEMO_ONLY === 'true';

export const queryClient = new QueryClient({defaultOptions:{queries:{retry:1,staleTime:15000,refetchOnWindowFocus:true}}});
let csrf: string | null = null;
export class ApiError extends Error {
  status: number;
  detail: Record<string, unknown>;
  constructor(status: number, detail: Record<string, unknown>) {
    super(String(detail.message || detail.detail || `HTTP ${status}`));
    this.status = status;
    this.detail = detail;
  }
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  if(demoOnly)return recordedRequest(path,options) as Promise<T>;
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (csrf && options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrf);
  const response = await fetch(`/api${path}`, {...options, headers, credentials:'same-origin'});
  const data = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data?.detail === 'object' && !Array.isArray(data.detail) ? data.detail : {message:typeof data?.detail === 'string' ? data.detail : JSON.stringify(data?.detail || data)};
    throw new ApiError(response.status, detail);
  }
  return data as T;
}
export async function getAuth(): Promise<Auth> {
  if(demoOnly)return {user:null,csrfToken:null,authMode:'recorded'};
  const result = await api<Auth>('/auth/me');
  csrf = result.csrfToken;
  return result;
}
export async function write<T>(path: string, data: unknown = {}, method = 'POST'): Promise<T> {
  return api<T>(path, {method,body:data instanceof FormData ? data : JSON.stringify(data)});
}
export function navigate(path: string) { window.location.hash = path; }
export function valueText(value: unknown): string {
  if (value === null || value === undefined) return '∅';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
export function displayTime(value?: unknown, timezone = 'Europe/Warsaw'): string {
  if (!value) return '∅';
  const s = String(value);
  try { return localParts(s, timezone).time || s; } catch { return s; }
}
