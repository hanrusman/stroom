export type ItemFormat = 'article' | 'podcast' | 'video' | 'short';

export interface Topic {
  slug: string;
  name: string;
  item_count: number;
}

export interface HuygensItem {
  id: string;
  title: string;
  description: string | null;
  author: string | null;
  thumbnail_url: string | null;
  media_url: string | null;
  source_name: string;
  source_image_url: string | null;
  published_at: string | null;
}

export interface Rail {
  format: ItemFormat;
  items: HuygensItem[];
}

export interface HuygensTopic {
  slug: string;
  name: string;
  rails: Rail[];
}

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

async function apiFetch(input: RequestInfo, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(input, { credentials: 'include', ...init });
  if (!r.ok) {
    let detail = `${r.status}`;
    try { const j = await r.clone().json(); detail = j.detail ?? detail; } catch {}
    throw new ApiError(r.status, detail);
  }
  return r;
}

export interface User { id: string; email: string; }

export async function fetchMe(): Promise<User> {
  const r = await apiFetch('/api/auth/me');
  return (await r.json()).user;
}

export async function login(email: string, password: string): Promise<User> {
  const r = await apiFetch('/api/auth/login', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  return (await r.json()).user;
}

export async function logout(): Promise<void> {
  await apiFetch('/api/auth/logout', { method: 'POST' });
}

export async function fetchTopics(): Promise<Topic[]> {
  const r = await apiFetch('/api/topics');
  return r.json();
}

export async function fetchHuygens(slug: string): Promise<HuygensTopic> {
  const r = await apiFetch(`/api/huygens/${slug}`);
  return r.json();
}

export type ItemStatus = 'new' | 'pinned' | 'later' | 'archived';
export type ProcessingStatus = 'pending' | 'queued' | 'transcribing' | 'summarizing' | 'ready' | 'failed';

export interface ItemDetail {
  id: string;
  format: ItemFormat;
  title: string;
  description: string | null;
  summary: string | null;
  summary_model: string | null;
  transcript: string | null;
  author: string | null;
  media_url: string | null;
  thumbnail_url: string | null;
  source_name: string;
  source_url: string;
  source_image_url: string | null;
  published_at: string | null;
  topics: string[];
  status: ItemStatus;
  processing_status: ProcessingStatus;
  queue_position: number | null;
  scheduled_for: string | null;
}

export async function fetchItem(id: string): Promise<ItemDetail> {
  const r = await apiFetch(`/api/huygens/items/${id}`);
  return r.json();
}

async function postAction(id: string, path: string, body?: unknown): Promise<ItemDetail> {
  const r = await apiFetch(`/api/huygens/items/${id}/${path}`, {
    method: 'POST',
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

export const setItemStatus = (id: string, status: ItemStatus) => postAction(id, 'status', { status });
export const summarizeItem  = (id: string) => postAction(id, 'summarize');
export const transcribeItem = (id: string) => postAction(id, 'transcribe');
export const scheduleItem   = (id: string, scheduled_for: string | null) =>
  postAction(id, 'schedule', { scheduled_for });

export interface Lesson {
  id: string;
  idx: number;
  title: string;
  body: string;
  rating: number | null;
  rated_at: string | null;
}

export async function fetchLessons(itemId: string): Promise<Lesson[]> {
  const r = await apiFetch(`/api/huygens/items/${itemId}/lessons`);
  return r.json();
}

export async function rateLesson(lessonId: string, rating: 1 | -1 | null): Promise<Lesson> {
  const r = await apiFetch(`/api/lessons/${lessonId}/rate`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ rating }),
  });
  return r.json();
}

export type ItemFilter = 'all' | 'saved' | 'summarized' | 'scheduled';
export type ItemWindow = 'all' | '24h' | '7d' | '30d';

export async function fetchFilteredItems(opts: {
  filter?: ItemFilter; window?: ItemWindow; topic?: string; limit?: number;
}): Promise<HuygensItem[]> {
  const p = new URLSearchParams();
  if (opts.filter && opts.filter !== 'all') p.set('filter', opts.filter);
  if (opts.window && opts.window !== 'all') p.set('window', opts.window);
  if (opts.topic) p.set('topic', opts.topic);
  p.set('limit', String(opts.limit ?? 100));
  const r = await apiFetch(`/api/huygens/items?${p.toString()}`);
  return r.json();
}

export interface TopicDigest {
  markdown: string | null;
  item_count: number | null;
  model: string | null;
  window_hours: number;
  generated_at: string | null;
  is_generating: boolean;
  error: string | null;
}

export async function fetchTopicDigest(slug: string): Promise<TopicDigest | null> {
  try {
    const r = await apiFetch(`/api/huygens/${slug}/digest`);
    return r.json();
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export type DigestModel = 'qwen' | 'sonnet' | 'opus';

export async function regenerateTopicDigest(slug: string, model: DigestModel = 'opus'): Promise<TopicDigest> {
  const r = await apiFetch(`/api/huygens/${slug}/digest?model=${model}`, { method: 'POST' });
  return r.json();
}

// --- Admin: sources ---

export type SourceKind = 'rss' | 'podcast' | 'youtube';

export interface AdminSource {
  id: string;
  name: string;
  url: string;
  kind: SourceKind;
  image_url: string | null;
  weight: number;
  max_per_rail: number | null;
  active: boolean;
  poll_interval_min: number;
  topic_slugs: string[];
  item_count: number;
}

export type AdminSourceUpdate = Partial<Omit<AdminSource, 'id' | 'item_count'>>;
export type AdminSourceCreate = Omit<AdminSource, 'id' | 'item_count'>;

export async function fetchAdminSources(): Promise<AdminSource[]> {
  const r = await apiFetch('/api/admin/sources');
  return r.json();
}

export async function updateAdminSource(id: string, patch: AdminSourceUpdate): Promise<AdminSource> {
  const r = await apiFetch(`/api/admin/sources/${id}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(patch),
  });
  return r.json();
}

export async function createAdminSource(body: AdminSourceCreate): Promise<AdminSource> {
  const r = await apiFetch('/api/admin/sources', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return r.json();
}

export async function deleteAdminSource(id: string): Promise<void> {
  await apiFetch(`/api/admin/sources/${id}`, { method: 'DELETE' });
}

export interface RefreshResult { ok: boolean; inserted: number; checked: number; }

export async function refreshAdminSource(id: string): Promise<RefreshResult> {
  const r = await apiFetch(`/api/admin/sources/${id}/refresh`, { method: 'POST' });
  return r.json();
}

export interface RefreshAllResult {
  ok: boolean;
  sources: number;
  errors: number;
  inserted: number;
  checked: number;
  thumbnails_scheduled?: number;
}

export async function refreshAllAdminSources(): Promise<RefreshAllResult> {
  const r = await apiFetch('/api/admin/sources/refresh-all', { method: 'POST' });
  return r.json();
}

export interface QueueItem {
  id: string;
  title: string;
  source_name: string;
  format: ItemFormat;
  processing_status: ProcessingStatus;
  queued_at: string | null;
  queue_position: number | null;
}

export async function fetchAdminQueue(): Promise<QueueItem[]> {
  const r = await apiFetch('/api/admin/queue');
  return r.json();
}
