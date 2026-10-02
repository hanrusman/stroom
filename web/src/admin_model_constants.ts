// De geldige modelset is dynamisch (zie fetchModels / GET /admin/models), dus
// DigestModel is een vrije string. MODEL_LABELS dient als fallback-label wanneer
// een model (nog) niet in de live lijst zit.
export type DigestModel = string;

export type ModelAction = 'expand' | 'distill' | 'digest' | 'digest_weekly' | 'ask' | 'score';

export const MODEL_LABELS: Record<string, string> = {
  qwen: 'Qwen3.6 35B (lokaal)',
  sonnet: 'Claude Sonnet 4.6',
  opus: 'Claude Opus 4.7',
  long: 'Gemini 2.5 Pro (lange context)',
  'cloud-kimi': 'Kimi K2.6 (cloud)',
  'cloud-qwen-coder': 'Qwen (uitgefaseerd)',
  'cloud-kimi-code': 'Kimi K2.7 Code (cloud)',
  'cloud-gpt-120b': 'gpt-oss 120B (cloud)',
  'cloud-gpt-20b': 'gpt-oss 20B (snel)',
  'cloud-gemma': 'Gemma 4 (cloud)',
  'cloud-minimax': 'MiniMax M3 (cloud)',
  'cloud-glm': 'GLM 5.3 (cloud)',
  'cloud-deepseek': 'DeepSeek V4-pro (cloud)',
  'cloud-mistral': 'Mistral Large 3 (cloud)',
  'cloud-nemotron': 'Nemotron 3 Ultra (cloud)',
};

// Vriendelijk label voor een Stroom-modelnaam — valt terug op de naam zelf.
export function modelLabel(name: string): string {
  return MODEL_LABELS[name] ?? name;
}

export const ALL_ACTIONS: ModelAction[] = ['expand','distill','digest','digest_weekly','ask','score'];

export const ACTION_LABELS: Record<ModelAction, string> = {
  expand: 'Verdiep deze les',
  distill: 'Meer lessen destilleren',
  digest: 'Dagdigest genereren',
  digest_weekly: 'Weekdigest genereren',
  ask: 'Vraag beantwoorden',
  score: 'Quality-score (1-10)',
};
