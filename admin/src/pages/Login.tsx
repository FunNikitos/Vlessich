/** Admin login page. */
import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Card, FormField, Input, PillButton, Turnstile } from "@/components";
import { useAuth } from "@/hooks/useAuth";
import { ApiError } from "@/lib/api";

const TURNSTILE_SITEKEY = import.meta.env.VITE_TURNSTILE_SITEKEY ?? "";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onCaptchaToken = useCallback((token: string) => {
    setCaptchaToken(token);
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password, captchaToken);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 429) setError("Слишком много попыток. Подождите.");
        else if (err.status === 401) setError("Неверные данные.");
        else if (err.code === "captcha_failed") setError("Captcha не пройдена. Обновите страницу.");
        else setError(err.message || "Ошибка входа");
      } else {
        setError("Сеть недоступна");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-base p-6">
      <Card className="w-full max-w-sm" padded>
        <h1 className="mb-6 font-title text-[20px] font-bold uppercase tracking-[2px] text-text-base">
          Vlessich · Admin
        </h1>
        <form onSubmit={onSubmit} className="space-y-4">
          <FormField label="Email" htmlFor="email">
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="username"
              disabled={loading}
            />
          </FormField>
          <FormField label="Password" htmlFor="password">
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              disabled={loading}
            />
          </FormField>
          {TURNSTILE_SITEKEY && (
            <Turnstile sitekey={TURNSTILE_SITEKEY} onToken={onCaptchaToken} />
          )}
          {error && (
            <p className="text-sm text-negative" role="alert">
              {error}
            </p>
          )}
          <PillButton
            type="submit"
            variant="primary"
            size="lg"
            loading={loading}
            className="w-full"
          >
            Sign in
          </PillButton>
        </form>
      </Card>
    </div>
  );
}
