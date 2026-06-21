import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { AppSettings, DigestModel, ModelAction, ModelInfo, fetchSettings, fetchModels, updateSettings } from './api';

const FALLBACK: AppSettings = { model_defaults: { expand: 'qwen', distill: 'qwen', digest: 'opus', digest_weekly: 'opus', ask: 'qwen', score: 'cloud-kimi' } };

interface Ctx {
  settings: AppSettings;
  models: ModelInfo[];
  loading: boolean;
  save: (s: AppSettings) => Promise<void>;
  getDefault: (action: ModelAction) => DigestModel;
}

const SettingsContext = createContext<Ctx | null>(null);

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<AppSettings>(FALLBACK);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSettings().then(setSettings).catch(() => {}).finally(() => setLoading(false));
    fetchModels().then(setModels).catch(() => {});
  }, []);

  const save = useCallback(async (s: AppSettings) => {
    const fresh = await updateSettings(s);
    setSettings(fresh);
  }, []);

  const getDefault = useCallback((action: ModelAction): DigestModel => {
    const override = localStorage.getItem(`stroom-model-${action}`);
    if (override) return override;
    return settings.model_defaults[action];
  }, [settings]);

  return (
    <SettingsContext.Provider value={{ settings, models, loading, save, getDefault }}>
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings(): Ctx {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('useSettings outside SettingsProvider');
  return ctx;
}

export function setUserOverride(action: ModelAction, model: DigestModel | null) {
  const k = `stroom-model-${action}`;
  if (model === null) localStorage.removeItem(k);
  else localStorage.setItem(k, model);
}
