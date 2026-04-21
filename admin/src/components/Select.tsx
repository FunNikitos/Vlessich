/** Select with same styling as Input. */
import { forwardRef } from "react";
import type { SelectHTMLAttributes } from "react";

export const Select = forwardRef<
  HTMLSelectElement,
  SelectHTMLAttributes<HTMLSelectElement>
>(function Select({ className, children, ...rest }, ref) {
  const cls = [
    "w-full rounded-md bg-bg-mid px-3 py-2.5 text-sm text-text-base",
    "border border-transparent focus:border-brand-green focus:outline-none",
    "disabled:cursor-not-allowed disabled:opacity-60",
    className ?? "",
  ].join(" ");
  return (
    <select ref={ref} className={cls} {...rest}>
      {children}
    </select>
  );
});
