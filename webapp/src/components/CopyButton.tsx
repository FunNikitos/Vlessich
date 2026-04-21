import { useState } from "react";
import { PillButton } from "./PillButton";

interface CopyButtonProps {
  value: string;
  label?: string;
}

/** Copy value to clipboard; 2s ephemeral feedback. */
export function CopyButton({ value, label = "Копировать" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  async function handle() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("clipboard write failed", err);
    }
  }

  return (
    <PillButton variant="secondary" size="sm" onClick={handle}>
      {copied ? "Скопировано" : label}
    </PillButton>
  );
}
