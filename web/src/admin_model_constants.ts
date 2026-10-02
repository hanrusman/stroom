// De geldige modelset is dynamisch (zie fetchModels / GET /admin/models), dus
// DigestModel is een vrije string. Labels komen mee uit die lijst (bron:
// model_info in vps-stacks/litellm/config.yaml).
export type DigestModel = string;

export type ModelAction = 'expand' | 'distill' | 'digest' | 'digest_weekly' | 'ask' | 'score';

export const ALL_ACTIONS: ModelAction[] = ['expand','distill','digest','digest_weekly','ask','score'];

export const ACTION_LABELS: Record<ModelAction, string> = {
  expand: 'Verdiep deze les',
  distill: 'Meer lessen destilleren',
  digest: 'Dagdigest genereren',
  digest_weekly: 'Weekdigest genereren',
  ask: 'Vraag beantwoorden',
  score: 'Quality-score (1-10)',
};
