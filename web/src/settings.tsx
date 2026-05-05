import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { AppSettings, DigestModel, ModelAction, fetchSettings, updateSettings } from './api';

const FALLBACK: AppSettings = { model_defaults: { expand: 'qwen', distill: 'qwen', digest: 'opus' } };

interface Ctx {
  settings: AppSettings;
  loading: boolean;
  save: (s: AppSettings) => Promise<void>;
  getDefault: (action: ModelAction) => DigestModel;
}

const SettingsContext = createContext<Ctx | null>(null);

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<AppSettings>(FALLBACK);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSettings().then(setSettings).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const save = useCallback(async (s: AppSettings) => {
    const fresh = await updateSettings(s);
    setSettings(fresh);
  }, []);

  const getDefault = useCallback((action: ModelAction): DigestModel => {
    const override = localStorage.getItem(`stroom-model-${action}`) as DigestModel | null;
    if (override === 'qwen' || override === 'sonnet' || override === 'opus') return override;
    return settings.model_defaults[action];
  }, [settings]);

  return (
    <SettingsContext.Provider value={{ settings, loading, save, getDefault }}>
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
