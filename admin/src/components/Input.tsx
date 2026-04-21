/** Spotify-dark input: #1f1f1f bg, focus → brand-green border. */
import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    const cls = [
      "w-full rounded-md bg-bg-mid px-3.5 py-2.5 text-sm text-text-base",
      "border border-transparent placeholder:text-text-muted",
      "focus:border-brand-green focus:outline-none",
      "disabled:cursor-not-allowed disabled:opacity-60",
      className ?? "",
    ].join(" ");
    return <input ref={ref} className={cls} {...rest} />;
  },
);
