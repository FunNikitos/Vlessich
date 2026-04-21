interface ToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  label: string;
}

/** Spotify-style pill toggle. Active = brand-green (#1ed760). */
export function Toggle({ checked, onChange, disabled = false, label }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={
        "relative inline-flex h-7 w-12 shrink-0 items-center rounded-pill transition-colors " +
        (checked ? "bg-brand-green" : "bg-bg-mid") +
        (disabled ? " opacity-50 cursor-not-allowed" : " cursor-pointer")
      }
    >
      <span
        className={
          "inline-block h-5 w-5 transform rounded-full bg-white transition-transform " +
          (checked ? "translate-x-6" : "translate-x-1")
        }
      />
    </button>
  );
}
