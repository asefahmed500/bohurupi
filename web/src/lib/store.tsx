"use client";

// Global client state: auth tokens, user, settings, languages, theme.

import * as React from "react";
import { toast } from "sonner";

import {
  getLanguages,
  getMe,
  getSettings,
  loadTokens,
  login as apiLogin,
  demoLogin,
  putSettings,
  register as apiRegister,
  saveTokens,
} from "@/lib/api";
import type { Language, User, UserSettings } from "@/lib/types";

interface AppState {
  ready: boolean;
  user: User | null;
  settings: UserSettings;
  languages: Language[];
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string) => Promise<void>;
  loginDemo: () => Promise<void>;
  logout: () => void;
  updateSettings: (patch: Partial<UserSettings>) => Promise<void>;
  setTokenFromOAuth: (token: string, refreshToken?: string) => Promise<void>;
}

const DEFAULT_SETTINGS: UserSettings = {
  theme: "system",
  default_lang: "auto",
  default_voice_id: "kokoro:af-heart",
  speed: 1,
  auto_play: true,
  captions: true,
  engine_pref: "quality",
};

const AppContext = React.createContext<AppState | null>(null);

export function useApp(): AppState {
  const ctx = React.useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside <AppProvider>");
  return ctx;
}

function applyTheme(theme: string) {
  const root = document.documentElement;
  const dark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  root.classList.toggle("dark", dark);
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = React.useState(false);
  const [user, setUser] = React.useState<User | null>(null);
  const [settings, setSettings] = React.useState<UserSettings>(DEFAULT_SETTINGS);
  const [languages, setLanguages] = React.useState<Language[]>([]);

  // bootstrap
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      const stored = typeof window !== "undefined" ? loadLocalTheme() : "system";
      applyTheme(stored);
      // /languages and /auth/me are independent — fetch in parallel
      const [langs, me] = await Promise.allSettled([getLanguages(), loadTokens() ? getMe() : null]);
      if (!cancelled && langs.status === "fulfilled") {
        setLanguages(langs.value.languages);
      }
      if (!cancelled && me.status === "fulfilled" && me.value) {
        setUser(me.value);
      }
      if (!cancelled && me.status === "rejected") {
        saveTokens(null);
      }
      if (loadTokens()) {
        try {
          const s = await getSettings();
          if (!cancelled) {
            setSettings(s);
            saveLocalTheme(s.theme);
            applyTheme(s.theme);
          }
        } catch {
          /* settings fall back to defaults */
        }
      }
      if (!cancelled) setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // follow system theme when set to system
  React.useEffect(() => {
    if (settings.theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [settings.theme]);

  const finishAuth = React.useCallback(async (tokens: { user: User }) => {
    setUser(tokens.user);
    try {
      const s = await getSettings();
      setSettings(s);
      saveLocalTheme(s.theme);
      applyTheme(s.theme);
    } catch {
      /* defaults are fine */
    }
  }, []);

  const login = React.useCallback(
    async (email: string, password: string) => {
      const tokens = await apiLogin(email, password);
      saveTokens(tokens);
      await finishAuth(tokens);
    },
    [finishAuth]
  );

  const register = React.useCallback(
    async (email: string, password: string, name: string) => {
      const tokens = await apiRegister(email, password, name);
      saveTokens(tokens);
      await finishAuth(tokens);
    },
    [finishAuth]
  );

  const loginDemo = React.useCallback(async () => {
    const tokens = await demoLogin();
    saveTokens(tokens);
    await finishAuth(tokens);
  }, [finishAuth]);

  const setTokenFromOAuth = React.useCallback(
    async (token: string, refreshToken = "") => {
      saveTokens({
        access_token: token,
        refresh_token: refreshToken,
        user: { id: "", email: "", name: "", role: "user", plan: "free", created_at: "" },
      });
      const me = await getMe();
      saveTokens({
        access_token: token,
        refresh_token: refreshToken,
        user: me,
      });
      await finishAuth({ user: me });
    },
    [finishAuth]
  );

  const logout = React.useCallback(() => {
    saveTokens(null);
    setUser(null);
    setSettings(DEFAULT_SETTINGS);
    toast("Signed out");
  }, []);

  const updateSettings = React.useCallback(
    async (patch: Partial<UserSettings>) => {
      setSettings((prev) => ({ ...prev, ...patch }));
      if (patch.theme !== undefined) {
        saveLocalTheme(patch.theme);
        applyTheme(patch.theme);
      }
      if (user) {
        try {
          const updated = await putSettings(patch);
          setSettings(updated);
        } catch {
          toast.error("Could not save settings");
        }
      }
    },
    [user]
  );

  const value: AppState = {
    ready,
    user,
    settings,
    languages,
    login,
    register,
    loginDemo,
    logout,
    updateSettings,
    setTokenFromOAuth,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

function loadLocalTheme(): string {
  try {
    return localStorage.getItem("bohurupi.theme") ?? "system";
  } catch {
    return "system";
  }
}

function saveLocalTheme(theme: string) {
  try {
    localStorage.setItem("bohurupi.theme", theme);
  } catch {
    /* ignore */
  }
}
