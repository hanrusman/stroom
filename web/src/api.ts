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
  source_id: string;
  source_name: string;
  source_image_url: string | null;
  published_at: string | null;
  format?: ItemFormat | null;
  status?: ItemStatus | null;
  processing_status?: ProcessingStatus | null;
  has_summary?: boolean;
  has_transcript?: boolean;
  scheduled_for?: string | null;
  quality_score?: number | null;
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
export type ProcessingStatus = 'pending' | 'queued' | 'transcribe_queued' | 'summarize_queued' | 'transcribing' | 'summarizing' | 'ready' | 'failed';

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
  speaker?: string | null;
}

export interface ItemDetail {
  id: string;
  format: ItemFormat;
  title: string;
  description: string | null;
  summary: string | null;
  summary_model: string | null;
  transcript: string | null;
  transcript_segments: TranscriptSegment[] | null;
  author: string | null;
  media_url: string | null;
  thumbnail_url: string | null;
  source_id: string;
  source_name: string;
  source_url: string;
  source_image_url: string | null;
  published_at: string | null;
  topics: string[];
  status: ItemStatus;
  processing_status: ProcessingStatus;
  queue_position: number | null;
  scheduled_for: string | null;
  quality_score: number | null;
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

export type ScoreChangeReason = 'auto' | 'wrong_topic' | 'too_many_ads' | 'low_quality' | 'high_quality' | 'personal_interest' | 'not_interesting' | 'other';

export interface QualityScoreUpdate {
  quality_score: number | null;
  reason?: ScoreChangeReason;
  note?: string;
}

export async function updateItemQualityScore(id: string, update: QualityScoreUpdate): Promise<ItemDetail> {
  const r = await apiFetch(`/api/huygens/items/${id}/quality-score`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(update),
  });
  return r.json();
}

export interface Lesson {
  id: string;
  idx: number;
  title: string;
  body: string;
  rating: number | null;
  rated_at: string | null;
  item_id: string;
  item_title: string;
  source_name: string;
  media_url: string | null;
  expansion: string | null;
  expansion_model: string | null;
  expansion_generated_at: string | null;
  vikunja_task_id?: number | null;
}

export async function fetchLessons(itemId: string): Promise<Lesson[]> {
  const r = await apiFetch(`/api/huygens/items/${itemId}/lessons`);
  return r.json();
}

export async function fetchAllLessons(rating?: 1 | -1 | null): Promise<Lesson[]> {
  const p = new URLSearchParams();
  if (rating === 1 || rating === -1) p.set('rating', String(rating));
  const r = await apiFetch(`/api/lessons${p.toString() ? '?' + p.toString() : ''}`);
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

export async function sendLessonToVikunja(lessonId: string): Promise<{ success: boolean; task_id: number; already_sent?: boolean }> {
  const r = await apiFetch(`/api/lessons/${lessonId}/send-to-vikunja`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
  });
  return r.json();
}

export type ItemFilter = 'all' | 'saved' | 'summarized' | 'scheduled' | 'archived' | 'inbox';
export type ItemWindow = 'all' | '24h' | '7d' | '30d';

export async function fetchFilteredItems(opts: {
  filter?: ItemFilter; window?: ItemWindow; topic?: string;
  source_id?: string; include_archived?: boolean;
  limit?: number; offset?: number;
}): Promise<HuygensItem[]> {
  const p = new URLSearchParams();
  if (opts.filter && opts.filter !== 'all') p.set('filter', opts.filter);
  if (opts.window && opts.window !== 'all') p.set('window', opts.window);
  if (opts.topic) p.set('topic', opts.topic);
  if (opts.source_id) p.set('source_id', opts.source_id);
  if (opts.include_archived) p.set('include_archived', 'true');
  p.set('limit', String(opts.limit ?? 100));
  if (opts.offset) p.set('offset', String(opts.offset));
  const r = await apiFetch(`/api/huygens/items?${p.toString()}`);
  return r.json();
}

export interface SourceDetail {
  id: string;
  name: string;
  url: string;
  kind: 'rss' | 'podcast' | 'youtube';
  image_url: string | null;
  item_count: number;
}

export async function fetchSourceDetail(id: string): Promise<SourceDetail> {
  const r = await apiFetch(`/api/sources/${id}`);
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

export type DigestWindow = 'daily' | 'weekly';

export async function fetchTopicDigest(slug: string, window: DigestWindow = 'daily'): Promise<TopicDigest | null> {
  try {
    const r = await apiFetch(`/api/huygens/${slug}/digest?window=${window}`);
    return r.json();
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

// DigestModel + ModelAction zijn verhuisd naar admin_model_constants.ts zodat
// het frontend de modellen op één plek beheert. Re-export voor backward-compat
// met bestaande call-sites die ze uit `./api` importeren.
export type { DigestModel, ModelAction } from './admin_model_constants';
import type { DigestModel } from './admin_model_constants';

export async function regenerateTopicDigest(slug: string, model: DigestModel = 'opus', window: DigestWindow = 'daily'): Promise<TopicDigest> {
  const r = await apiFetch(`/api/huygens/${slug}/digest?model=${model}&window=${window}`, { method: 'POST' });
  return r.json();
}

// --- Lessons: distill / expand / digest ---

export async function distillMoreLessons(itemId: string, model: DigestModel = 'opus'): Promise<Lesson[]> {
  const r = await apiFetch(`/api/huygens/items/${itemId}/lessons/distill?model=${model}`, { method: 'POST' });
  return r.json();
}

export async function expandLesson(lessonId: string, model: DigestModel = 'opus', force = false): Promise<Lesson> {
  const p = new URLSearchParams({ model });
  if (force) p.set('force', 'true');
  const r = await apiFetch(`/api/lessons/${lessonId}/expand?${p.toString()}`, { method: 'POST' });
  return r.json();
}

export type LessonsDigestFilter = 'useful' | 'not-useful' | 'all';

export interface LessonsDigest {
  markdown: string | null;
  lesson_count: number | null;
  model: string | null;
  window_hours: number;
  rating: number;
  generated_at: string | null;
  is_generating: boolean;
  error: string | null;
}

export async function fetchLessonsDigest(window: DigestWindow = 'weekly', filter: LessonsDigestFilter = 'useful'): Promise<LessonsDigest | null> {
  try {
    const r = await apiFetch(`/api/lessons/digest?window=${window}&filter=${filter}`);
    return r.json();
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export async function regenerateLessonsDigest(model: DigestModel = 'opus', window: DigestWindow = 'weekly', filter: LessonsDigestFilter = 'useful'): Promise<LessonsDigest> {
  const r = await apiFetch(`/api/lessons/digest?model=${model}&window=${window}&filter=${filter}`, { method: 'POST' });
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

export interface CronResult {
  ok: boolean;
  [key: string]: unknown;
}

export async function cronTranscribePodcasts(hours = 24): Promise<CronResult> {
  const r = await apiFetch(`/api/admin/cron/transcribe-podcasts?hours=${hours}`, { method: 'POST' });
  return r.json();
}
export async function cronTranscribeVideos(hours = 24): Promise<CronResult> {
  const r = await apiFetch(`/api/admin/cron/transcribe-videos?hours=${hours}`, { method: 'POST' });
  return r.json();
}
export async function cronSummarizeArticles(hours = 24): Promise<CronResult> {
  const r = await apiFetch(`/api/admin/cron/summarize-articles?hours=${hours}`, { method: 'POST' });
  return r.json();
}
export async function cronDigestTopics(window: 'daily' | 'weekly' = 'daily',
                                       model?: DigestModel): Promise<CronResult> {
  const q = `window=${window}` + (model ? `&model=${model}` : '');
  const r = await apiFetch(`/api/admin/cron/digest-topics?${q}`, { method: 'POST' });
  return r.json();
}

export async function removeFromQueue(itemId: string): Promise<void> {
  await apiFetch(`/api/admin/queue/${itemId}`, { method: 'DELETE' });
}

export async function restartQueue(): Promise<CronResult> {
  const r = await apiFetch('/api/admin/queue/restart', { method: 'POST' });
  return r.json();
}

export interface BulkArchiveRequest {
  topic_slugs: string[];
  older_than_days: number;
  weight_max: number;
  formats: string[];
}

export interface BulkArchiveResponse {
  archived: number;
}

export async function bulkArchive(body: BulkArchiveRequest): Promise<BulkArchiveResponse> {
  const r = await apiFetch('/api/admin/items/bulk-archive', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return r.json();
}

export interface DigestStatus {
  window: string;
  in_progress: number;
  done: number;
  failed: number;
}
export async function fetchDigestStatus(window: 'daily' | 'weekly' = 'daily'): Promise<DigestStatus> {
  const r = await apiFetch(`/api/admin/cron/digest-status?window=${window}`);
  return r.json();
}

export interface TopicDigestRun {
  id: string;
  generated_at: string;
  model: string | null;
  item_count: number | null;
  markdown: string;
}
export async function fetchTopicDigestHistory(slug: string, window: 'daily' | 'weekly' = 'daily',
                                              limit = 7): Promise<TopicDigestRun[]> {
  const r = await apiFetch(`/api/huygens/${slug}/digest/history?window=${window}&limit=${limit}`);
  return r.json();
}

// ModelAction is verhuisd naar admin_model_constants.ts (zie hierboven).

export interface ModelDefaults {
  expand: DigestModel;
  distill: DigestModel;
  digest: DigestModel;
  ask: DigestModel;
  score: DigestModel;
}

export interface AskAnswer {
  id?: string;
  question: string;
  answer: string;
  model: DigestModel;
  sources_used: string[];
  created_at?: string;
}

export async function askItem(itemId: string, question: string, model: DigestModel = 'qwen'): Promise<AskAnswer> {
  const r = await apiFetch(`/api/huygens/items/${itemId}/ask?model=${model}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  });
  return r.json();
}

export async function fetchItemQuestions(itemId: string, limit: number = 20): Promise<AskAnswer[]> {
  const r = await apiFetch(`/api/huygens/items/${itemId}/questions?limit=${limit}`);
  return r.json();
}

export async function deleteQuestion(itemId: string, questionId: string): Promise<void> {
  await apiFetch(`/api/huygens/items/${itemId}/questions/${questionId}`, {
    method: 'DELETE',
  });
}

export interface AppSettings {
  model_defaults: ModelDefaults;
}

export async function fetchSettings(): Promise<AppSettings> {
  const r = await apiFetch('/api/admin/settings');
  return r.json();
}

export interface AdminTopic {
  slug: string;
  name: string;
  sort_order: number;
  item_count: number;
  source_count: number;
}

export async function fetchAdminTopics(): Promise<AdminTopic[]> {
  const r = await apiFetch('/api/admin/topics');
  return r.json();
}

export async function updateTopicOrder(slugs: string[]): Promise<void> {
  await apiFetch('/api/admin/topics/order', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slugs }),
  });
}

export async function deleteTopic(slug: string, reassignTo: string): Promise<void> {
  await apiFetch(`/api/admin/topics/${encodeURIComponent(slug)}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reassign_to: reassignTo }),
  });
}

export interface AdminStats {
  total_items: number;
  total_sources: number;
  status_breakdown: Record<string, number>;
  type_breakdown: Record<string, number>;
  type_breakdown_24h: Record<string, number>;
  queue: {
    summarize_queued: number;
    summarizing: number;
    transcribe_queued: number;
    transcribing: number;
  };
  recent_items: {
    hours_24: number;
    days_7: number;
  };
}

export async function fetchAdminStats(): Promise<AdminStats> {
  const r = await apiFetch('/api/admin/stats');
  return r.json();
}

export async function updateSettings(s: AppSettings): Promise<AppSettings> {
  const r = await apiFetch('/api/admin/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(s),
  });
  return r.json();
}

// --- Item Topics ---

export async function addItemToTopic(itemId: string, topicSlug: string): Promise<ItemDetail> {
  const r = await apiFetch(`/api/huygens/items/${itemId}/topics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic_slug: topicSlug }),
  });
  return r.json();
}

export async function removeItemTopic(itemId: string, topicSlug: string): Promise<ItemDetail> {
  const r = await apiFetch(`/api/huygens/items/${itemId}/topics/${topicSlug}`, {
    method: 'DELETE',
  });
  return r.json();
}

// --- Quality Scorer Admin ---

export interface QualityScorerTopic {
  name: string;
  keywords: string[];
}

export interface QualityScorerPerson {
  name: string;
  keywords: string[];
}

export async function fetchQualityScorerTopics(): Promise<{ topics: Record<string, string[]>; count: number }> {
  const r = await apiFetch('/api/admin/quality-scorer/topics');
  return r.json();
}

export async function fetchQualityScorerPersons(): Promise<{ persons: Record<string, string[]>; count: number }> {
  const r = await apiFetch('/api/admin/quality-scorer/persons');
  return r.json();
}

export async function createQualityScorerTopic(topic: QualityScorerTopic): Promise<{ status: string; topic: string }> {
  const r = await apiFetch('/api/admin/quality-scorer/topics', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(topic),
  });
  return r.json();
}

export async function updateQualityScorerTopic(name: string, keywords: string[]): Promise<{ status: string; topic: string }> {
  const r = await apiFetch(`/api/admin/quality-scorer/topics/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keywords }),
  });
  return r.json();
}

export async function deleteQualityScorerTopic(name: string): Promise<{ status: string; topic: string }> {
  const r = await apiFetch(`/api/admin/quality-scorer/topics/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
  return r.json();
}

export async function createQualityScorerPerson(person: QualityScorerPerson): Promise<{ status: string; person: string }> {
  const r = await apiFetch('/api/admin/quality-scorer/persons', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(person),
  });
  return r.json();
}

export async function updateQualityScorerPerson(name: string, keywords: string[]): Promise<{ status: string; person: string }> {
  const r = await apiFetch(`/api/admin/quality-scorer/persons/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keywords }),
  });
  return r.json();
}

export async function deleteQualityScorerPerson(name: string): Promise<{ status: string; person: string }> {
  const r = await apiFetch(`/api/admin/quality-scorer/persons/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
  return r.json();
}

export async function reloadQualityScorerConfig(): Promise<{ status: string; topics: string[]; persons: string[] }> {
  const r = await apiFetch('/api/admin/quality-scorer/reload', {
    method: 'POST',
  });
  return r.json();
}

export interface ExtractedKeyword {
  term: string;
  score: number;
  type: 'bigram' | 'unigram';
}

export interface ExtractKeywordsResponse {
  keywords: ExtractedKeyword[];
  persons_mentioned: string[];
  topics_matched: string[];
}

export async function extractKeywords(text: string, title?: string): Promise<ExtractKeywordsResponse> {
  const r = await apiFetch('/api/admin/quality-scorer/extract-keywords', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: text.slice(0, 5000), title, max_keywords: 15 }),
  });
  return r.json();
}

// --- Inbox ---

export interface InboxSubmitRequest {
  url: string;
  title: string;
  format: 'article' | 'podcast' | 'video';
  topic_slug: string;
  description?: string | null;
  author?: string | null;
}

export interface InboxSubmitResponse {
  id: string;
  title: string;
  message: string;
}

export async function submitToInbox(body: InboxSubmitRequest): Promise<InboxSubmitResponse> {
  const r = await apiFetch('/api/inbox/submit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return r.json();
}

export interface InboxFetchRequest {
  url: string;
}

export interface InboxFetchResponse {
  url: string;
  title: string | null;
  description: string | null;
  author: string | null;
  format: 'article' | 'podcast' | 'video';
  thumbnail_url: string | null;
}

export async function fetchInboxMetadata(body: InboxFetchRequest): Promise<InboxFetchResponse> {
  const r = await apiFetch('/api/inbox/fetch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return r.json();
}

export async function fetchInboxTopics(): Promise<{ slug: string; name: string }[]> {
  const r = await apiFetch('/api/inbox/topics');
  return r.json();
}
