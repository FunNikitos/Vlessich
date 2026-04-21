/** Side drawer (right-anchored). Portal + backdrop + esc. */
import { useEffect } from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  width?: string;
}

export function Drawer({
  open,
  onClose,
  title,
  children,
  width = "560px",
}: DrawerProps) {
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
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
    >
      <aside
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        style={{ width }}
        className="absolute right-0 top-0 h-full max-w-full overflow-y-auto bg-bg-elevated shadow-elevated"
      >
        {title && (
          <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border-base/40 bg-bg-elevated px-6 py-4">
            <h3 className="font-title text-[13px] font-bold uppercase tracking-[2px] text-text-base">
              {title}
            </h3>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded-pill px-3 py-1 text-[11px] font-bold uppercase tracking-[1.6px] text-text-muted hover:bg-bg-mid hover:text-text-base"
            >
              Close
            </button>
          </header>
        )}
        <div className="px-6 py-5">{children}</div>
      </aside>
    </div>,
    document.body,
  );
}
