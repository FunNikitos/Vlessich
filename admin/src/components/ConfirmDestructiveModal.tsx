/** Confirm modal with "type to confirm" input. */
import { useState } from "react";
import { FormField, Input, Modal, PillButton } from "@/components";

interface Props {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  body: string;
  confirmWord?: string;
  confirmLabel?: string;
  loading?: boolean;
  error?: string | null;
}

export function ConfirmDestructiveModal({
  open,
  onClose,
  onConfirm,
  title,
  body,
  confirmWord = "REVOKE",
  confirmLabel = "Revoke",
  loading = false,
  error,
}: Props) {
  const [typed, setTyped] = useState("");
  const matches = typed.trim() === confirmWord;

  function close() {
    setTyped("");
    onClose();
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title={title}
      actions={
        <>
          <PillButton variant="ghost" onClick={close} disabled={loading}>
            Cancel
          </PillButton>
          <PillButton
            variant="danger"
            onClick={onConfirm}
            disabled={!matches}
            loading={loading}
          >
            {confirmLabel}
          </PillButton>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-text-base">{body}</p>
        <FormField
          label={`Type ${confirmWord} to confirm`}
          error={error ?? null}
        >
          <Input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoFocus
          />
        </FormField>
      </div>
    </Modal>
  );
}
