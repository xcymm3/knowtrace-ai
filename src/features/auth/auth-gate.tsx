"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import type { Session } from "@supabase/supabase-js";

import styles from "@/app/page.module.css";
import { WorkspaceClient } from "@/features/workspace/workspace-client";
import { knowTraceApi } from "@/lib/knowtrace-api";
import { getSupabaseBrowserClient, supabaseAuthConfigured } from "@/lib/supabase-browser";

type AuthMode = "sign-in" | "sign-up";

const usernamePattern = /^[A-Za-z0-9_-]{3,32}$/;
const e2eTestMode = process.env.NEXT_PUBLIC_E2E_TEST_MODE === "true";

function e2eSession(): Session | null {
  if (!e2eTestMode || typeof window === "undefined") return null;
  if (window.localStorage.getItem("knowtrace-e2e-session") !== "signed-in") return null;
  return {
    access_token: "e2e-access-token",
    refresh_token: "e2e-refresh-token",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    token_type: "bearer",
    user: {
      id: "44444444-4444-4444-8444-444444444444",
      aud: "authenticated",
      role: "authenticated",
      email: "e2e@example.com",
      user_metadata: { username: "e2e-user" },
    },
  } as unknown as Session;
}

function displayName(session: Session) {
  const username = session.user.user_metadata.username;
  if (typeof username === "string" && username.trim()) return username.trim();
  return session.user.email?.split("@")[0] ?? "当前用户";
}

function passwordStrength(password: string) {
  if (!password) return { level: 0, label: "输入密码后显示强度" };
  let level = 1;
  if (password.length >= 8) level += 1;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) level += 1;
  if (/\d/.test(password) || /[^A-Za-z0-9]/.test(password)) level += 1;
  return {
    level,
    label: ["", "较弱", "一般", "良好", "较强"][level],
  };
}

export function AuthGate() {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(supabaseAuthConfigured);

  useEffect(() => {
    if (e2eTestMode) {
      const frameId = window.requestAnimationFrame(() => {
        setSession(e2eSession());
        setIsLoading(false);
      });
      return () => window.cancelAnimationFrame(frameId);
    }
    if (!supabaseAuthConfigured) return;
    const supabase = getSupabaseBrowserClient();
    let active = true;
    void supabase.auth.getSession()
      .then(({ data }) => {
        if (active) setSession(data.session);
      })
      .catch(() => {
        if (active) setSession(null);
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setIsLoading(false);
    });
    return () => {
      active = false;
      listener.subscription.unsubscribe();
    };
  }, []);

  if (isLoading) {
    return <main className={styles.authShell}><p className={styles.authLoading}>正在恢复登录状态…</p></main>;
  }
  if (!supabaseAuthConfigured) {
    return <main className={styles.authShell}><section className={styles.authCard}><p className={styles.eyebrow}>配置缺失</p><h1>尚未启用登录</h1><p>请在 .env 中填写 NEXT_PUBLIC_SUPABASE_URL 与 NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY，然后重新构建前端。</p></section></main>;
  }
  if (!session) return <AuthForm />;

  return (
    <WorkspaceClient
      userEmail={session.user.email ?? null}
      userName={displayName(session)}
      onSignOut={() => getSupabaseBrowserClient().auth.signOut()}
    />
  );
}

function AuthForm() {
  const [mode, setMode] = useState<AuthMode>("sign-in");
  const [identity, setIdentity] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const strength = useMemo(() => passwordStrength(password), [password]);

  function switchMode() {
    setMode((current) => current === "sign-in" ? "sign-up" : "sign-in");
    setError(null);
    setNotice(null);
    setPassword("");
    setConfirmation("");
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedEmail = email.trim().toLowerCase();
    const normalizedUsername = username.trim();
    const normalizedIdentity = identity.trim();
    if (!password) {
      setError("请输入密码。");
      return;
    }
    if (mode === "sign-up") {
      if (!normalizedEmail) {
        setError("请输入有效邮箱。");
        return;
      }
      if (!usernamePattern.test(normalizedUsername)) {
        setError("用户名需为 3–32 位字母、数字、下划线或连字符。");
        return;
      }
      if (password !== confirmation) {
        setError("两次输入的密码不一致。");
        return;
      }
    } else if (!normalizedIdentity) {
      setError("请输入邮箱或用户名。");
      return;
    }

    setError(null);
    setNotice(null);
    setIsSubmitting(true);
    const supabase = getSupabaseBrowserClient();
    try {
      if (mode === "sign-in") {
        const nextSession = await knowTraceApi.signInWithIdentity(normalizedIdentity, password);
        const { error: sessionError } = await supabase.auth.setSession({
          access_token: nextSession.access_token,
          refresh_token: nextSession.refresh_token,
        });
        if (sessionError) throw sessionError;
      } else {
        const { data, error: signUpError } = await supabase.auth.signUp({
          email: normalizedEmail,
          password,
          options: { data: { username: normalizedUsername } },
        });
        if (signUpError) throw signUpError;
        if (!data.session) setNotice("注册成功。请前往邮箱完成验证后，用邮箱或用户名登录。");
      }
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "登录失败，请稍后重试。");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className={styles.authShell}>
      <section className={styles.authCard} aria-labelledby="auth-title">
        <a className={styles.brand} href="#auth-title"><span className={styles.brandMark} aria-hidden="true">◫</span>KnowTrace</a>
        <p className={styles.eyebrow}>个人知识工作台</p>
        <h1 id="auth-title">{mode === "sign-in" ? "登录，继续追溯你的资料。" : "创建你的知识工作台。"}</h1>
        <p className={styles.authDescription}>每个账号拥有独立的知识库、资料索引与对话记录。</p>
        <form className={styles.authForm} onSubmit={handleSubmit}>
          {mode === "sign-in" ? (
            <div className={styles.authField}>
              <label htmlFor="identity">邮箱或用户名</label>
              <input id="identity" type="text" autoComplete="username" value={identity} onChange={(event) => setIdentity(event.target.value)} placeholder="name@example.com 或 knowtrace" required disabled={isSubmitting} />
            </div>
          ) : (
            <>
              <div className={styles.authField}>
                <label htmlFor="username">用户名</label>
                <input id="username" type="text" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="3–32 位字母、数字、_ 或 -" required disabled={isSubmitting} />
              </div>
              <div className={styles.authField}>
                <label htmlFor="email">邮箱</label>
                <input id="email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" required disabled={isSubmitting} />
              </div>
            </>
          )}
          <div className={styles.authField}>
            <label htmlFor="password">密码</label>
            <input id="password" type="password" autoComplete={mode === "sign-in" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="请输入密码" required disabled={isSubmitting} />
            {mode === "sign-up" ? (
              <div className={styles.passwordStrength} data-level={strength.level} aria-label={`密码强度：${strength.label}`}>
                <span /><span /><span /><span />
                <p>密码强度：<strong>{strength.label}</strong><em>不影响注册</em></p>
              </div>
            ) : null}
          </div>
          {mode === "sign-up" ? (
            <div className={styles.authField}>
              <label htmlFor="confirmation">确认密码</label>
              <input id="confirmation" type="password" autoComplete="new-password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder="再次输入密码" required disabled={isSubmitting} />
              {confirmation ? <p className={password === confirmation ? styles.passwordMatch : styles.passwordMismatch}>{password === confirmation ? "两次密码一致" : "两次密码不一致"}</p> : null}
            </div>
          ) : null}
          {error ? <p className={styles.authError} role="alert">{error}</p> : null}
          {notice ? <p className={styles.authNotice} role="status">{notice}</p> : null}
          <button className={styles.primaryButton} type="submit" disabled={isSubmitting}>{isSubmitting ? "请稍候…" : mode === "sign-in" ? "登录" : "创建账号"}</button>
        </form>
        <button className={styles.authModeButton} type="button" onClick={switchMode} disabled={isSubmitting}>{mode === "sign-in" ? "没有账号？创建一个" : "已有账号？前往登录"}</button>
      </section>
    </main>
  );
}
