export type DigestModel =
  | 'qwen' | 'sonnet' | 'opus' | 'long'
  | 'cloud-kimi' | 'cloud-qwen-coder' | 'cloud-gpt-120b'
  | 'cloud-gpt-20b' | 'cloud-gemma';

export type ModelAction = 'expand' | 'distill' | 'digest' | 'ask' | 'score';

export const ALL_MODELS: DigestModel[] = [
  'qwen','sonnet','opus','long',
  'cloud-kimi','cloud-qwen-coder','cloud-gpt-120b','cloud-gpt-20b','cloud-gemma',
] as const;

export const MODEL_LABELS: Record<DigestModel, string> = {
  qwen: 'Qwen (lokaal)',
  sonnet: 'Claude Sonnet',
  opus: 'Claude Opus',
  long: 'Gemini 2.5 Pro (lange context)',
  'cloud-kimi': 'Kimi K2 (cloud)',
  'cloud-qwen-coder': 'Qwen3-coder 480B (cloud)',
  'cloud-gpt-120b': 'gpt-oss 120B (cloud)',
  'cloud-gpt-20b': 'gpt-oss 20B (snel)',
  'cloud-gemma': 'Gemma3 27B (cloud)',
};

export const ALL_ACTIONS: ModelAction[] = ['expand','distill','digest','ask','score'];

export const ACTION_LABELS: Record<ModelAction, string> = {
  expand: 'Verdiep deze les',
  distill: 'Meer lessen destilleren',
  digest: 'Digest genereren',
  ask: 'Vraag beantwoorden',
  score: 'Quality-score (1-10)',
};
