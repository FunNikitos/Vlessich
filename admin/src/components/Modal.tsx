/** Portal modal with backdrop + esc-to-close. */
import { useEffect } from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  size?: "sm" | "md" | "lg";
}

const SIZE_CLS: Record<NonNullable<ModalProps["size"]>, string> = {
  sm: "max-w-md",
  md: "max-w-xl",
  lg: "max-w-3xl",
};

export function Modal({
  open,
  onClose,
  title,
  children,
  actions,
  size = "md",
}: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div
      role="presentation"
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
    >
      <div
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        className={[
          "w-full rounded-xl bg-bg-elevated shadow-elevated",
          SIZE_CLS[size],
        ].join(" ")}
      >
        {title && (
          <div className="border-b border-border-base/40 px-6 py-4">
            <h3 className="font-title text-[13px] font-bold uppercase tracking-[2px] text-text-base">
              {title}
            </h3>
          </div>
        )}
        <div className="px-6 py-5">{children}</div>
        {actions && (
          <div className="flex justify-end gap-2 border-t border-border-base/40 px-6 py-4">
            {actions}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
