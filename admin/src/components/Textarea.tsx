/** Textarea (monospace available via class override). */
import { forwardRef } from "react";
import type { TextareaHTMLAttributes } from "react";

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, rows = 4, ...rest }, ref) {
  const cls = [
    "w-full rounded-md bg-bg-mid px-3.5 py-2.5 text-sm text-text-base",
    "border border-transparent focus:border-brand-green focus:outline-none",
    "disabled:cursor-not-allowed disabled:opacity-60",
    className ?? "",
  ].join(" ");
  return <textarea ref={ref} rows={rows} className={cls} {...rest} />;
});
