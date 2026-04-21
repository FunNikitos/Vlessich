/** Cloudflare Turnstile widget loader.
 *
 * Renders the Turnstile widget into a div ref and resolves the response
 * token via the supplied callback. The script is loaded once per page;
 * if the sitekey is empty the component renders nothing (dev mode).
 */
import { useEffect, useRef } from "react";

const SCRIPT_SRC =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
const SCRIPT_ID = "vlessich-turnstile-script";

interface TurnstileApi {
  render: (
    el: HTMLElement,
    opts: { sitekey: string; callback: (token: string) => void; theme?: "dark" | "light" | "auto" },
  ) => string;
  reset: (widgetId?: string) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

let scriptPromise: Promise<void> | null = null;

function loadScript(): Promise<void> {
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise((resolve, reject) => {
    if (typeof window === "undefined") {
      reject(new Error("no window"));
      return;
    }
    if (window.turnstile) {
      resolve();
      return;
    }
    const existing = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null;
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("script error")));
      return;
    }
    const s = document.createElement("script");
    s.id = SCRIPT_ID;
    s.src = SCRIPT_SRC;
    s.async = true;
    s.defer = true;
    s.addEventListener("load", () => resolve());
    s.addEventListener("error", () => reject(new Error("script error")));
    document.head.appendChild(s);
  });
  return scriptPromise;
}

interface Props {
  sitekey: string;
  onToken: (token: string) => void;
}

export function Turnstile({ sitekey, onToken }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!sitekey) return;
    let cancelled = false;
    loadScript()
      .then(() => {
        if (cancelled || !ref.current || !window.turnstile) return;
        widgetIdRef.current = window.turnstile.render(ref.current, {
          sitekey,
          theme: "dark",
          callback: (token: string) => onToken(token),
        });
      })
      .catch(() => {
        // Network blocked or script failed; widget simply does not appear.
        // Backend will reject login with captcha_failed if it requires one.
      });
    return () => {
      cancelled = true;
      if (window.turnstile && widgetIdRef.current) {
        window.turnstile.reset(widgetIdRef.current);
      }
    };
  }, [sitekey, onToken]);

  if (!sitekey) return null;
  return <div ref={ref} className="flex justify-center" />;
}
