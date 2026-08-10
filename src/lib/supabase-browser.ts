import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabasePublishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
const e2eTestMode = process.env.NEXT_PUBLIC_E2E_TEST_MODE === "true";

export const supabaseAuthConfigured = Boolean(supabaseUrl && supabasePublishableKey);

let browserClient: SupabaseClient | null = null;

export function getSupabaseBrowserClient(): SupabaseClient {
  if (!supabaseUrl || !supabasePublishableKey) {
    throw new Error("缺少 Supabase 登录配置，请填写 NEXT_PUBLIC_SUPABASE_URL 和 NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY。");
  }
  browserClient ??= createClient(supabaseUrl, supabasePublishableKey);
  return browserClient;
}

export async function getAccessToken(): Promise<string | null> {
  if (e2eTestMode && typeof window !== "undefined") {
    return window.localStorage.getItem("knowtrace-e2e-session") === "signed-in"
      ? "e2e-access-token"
      : null;
  }
  const { data, error } = await getSupabaseBrowserClient().auth.getSession();
  if (error) throw error;
  return data.session?.access_token ?? null;
}
