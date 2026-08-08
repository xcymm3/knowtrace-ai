"use client";

import { FormEvent, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";

import styles from "@/app/page.module.css";
import { getSupabaseBrowserClient, supabaseAuthConfigured } from "@/lib/supabase-browser";
import { WorkspaceClient } from "@/features/workspace/workspace-client";

type AuthMode = "sign-in" | "sign-up";

export function AuthGate() {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(supabaseAuthConfigured);

  useEffect(() => {
    if (!supabaseAuthConfigured) return;
    const supabase = getSupabaseBrowserClient();
    void supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setIsLoading(false);
    });
    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setIsLoading(false);
    });
    return () => listener.subscription.unsubscribe();
  }, []);

  if (isLoading) {
    return <main className={styles.authShell}><p className={styles.authLoading}>正在恢复登录状态…</p></main>;
  }
  if (!supabaseAuthConfigured) {
    return <main className={styles.authShell}><section className={styles.authCard}><p className={styles.eyebrow}>配置缺失</p><h1>尚未启用登录</h1><p>请在 .env 中填写 NEXT_PUBLIC_SUPABASE_URL 与 NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY，然后重新构建前端。</p></section></main>;
  }
  if (!session) return <AuthForm />;

  return <WorkspaceClient userEmail={session.user.email ?? null} onSignOut={() => getSupabaseBrowserClient().auth.signOut()} />;
}

function AuthForm() {
  const [mode, setMode] = useState<AuthMode>("sign-in");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "").trim();
    const password = String(form.get("password") ?? "");
    if (!email || password.length < 8) {
      setError("请输入有效邮箱，密码至少需要 8 位。");
      return;
    }

    setError(null);
    setNotice(null);
    setIsSubmitting(true);
    const supabase = getSupabaseBrowserClient();
    try {
      if (mode === "sign-in") {
        const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
        if (signInError) throw signInError;
      } else {
        const { data, error: signUpError } = await supabase.auth.signUp({ email, password });
        if (signUpError) throw signUpError;
        if (!data.session) setNotice("注册成功。请前往邮箱完成验证后再登录。");
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
        <p className={styles.eyebrow}>个人知识库</p>
        <h1 id="auth-title">{mode === "sign-in" ? "登录后管理自己的资料。" : "创建个人知识库账号。"}</h1>
        <p className={styles.authDescription}>资料、索引与对话会按登录账号隔离保存。</p>
        <form className={styles.authForm} onSubmit={handleSubmit}>
          <label htmlFor="email">邮箱</label>
          <input id="email" name="email" type="email" autoComplete="email" placeholder="name@example.com" required disabled={isSubmitting} />
          <label htmlFor="password">密码</label>
          <input id="password" name="password" type="password" autoComplete={mode === "sign-in" ? "current-password" : "new-password"} minLength={8} placeholder="至少 8 位" required disabled={isSubmitting} />
          {error ? <p className={styles.authError} role="alert">{error}</p> : null}
          {notice ? <p className={styles.authNotice} role="status">{notice}</p> : null}
          <button className={styles.primaryButton} type="submit" disabled={isSubmitting}>{isSubmitting ? "请稍候…" : mode === "sign-in" ? "登录" : "注册"}</button>
        </form>
        <button className={styles.authModeButton} type="button" onClick={() => { setMode((current) => current === "sign-in" ? "sign-up" : "sign-in"); setError(null); setNotice(null); }} disabled={isSubmitting}>{mode === "sign-in" ? "没有账号？创建一个" : "已有账号？前往登录"}</button>
      </section>
    </main>
  );
}
