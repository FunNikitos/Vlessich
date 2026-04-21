/** Two-step modal: form → one-time plaintext display. */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FormField,
  Input,
  Modal,
  PillButton,
  Select,
  Textarea,
} from "@/components";
import { api, ApiError } from "@/lib/api";
import type { CodeBatchCreateIn, CodeBatchCreateOut } from "@/lib/types";

interface Props {
  open: boolean;
  onClose: () => void;
}

interface FormState {
  plan_name: string;
  duration_days: number;
  devices_limit: number;
  count: number;
  valid_days: number;
  tag: string;
  note: string;
  location: string;
}

const DEFAULTS: FormState = {
  plan_name: "1m",
  duration_days: 30,
  devices_limit: 3,
  count: 10,
  valid_days: 30,
  tag: "",
  note: "",
  location: "fi",
};

export function CreateCodesModal({ open, onClose }: Props) {
  const qc = useQueryClient();
  const [form, setForm] = useState<FormState>(DEFAULTS);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [created, setCreated] = useState<CodeBatchCreateOut | null>(null);
  const [apiErr, setApiErr] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (body: CodeBatchCreateIn) => api.codes.create(body),
    onSuccess: (data) => {
      setCreated(data);
      qc.invalidateQueries({ queryKey: ["codes"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (err) => {
      setApiErr(err instanceof ApiError ? err.message : "Ошибка");
    },
  });

  function validate(s: FormState): Record<string, string> {
    const e: Record<string, string> = {};
    if (!s.plan_name.trim()) e.plan_name = "Обязательно";
    if (s.duration_days < 1 || s.duration_days > 3650) e.duration_days = "1..3650";
    if (s.devices_limit < 1 || s.devices_limit > 5) e.devices_limit = "1..5";
    if (s.count < 1 || s.count > 500) e.count = "1..500";
    if (s.valid_days < 1 || s.valid_days > 365) e.valid_days = "1..365";
    if (!s.location.trim()) e.location = "Обязательно";
    return e;
  }

  function handleSubmit() {
    const ve = validate(form);
    setErrors(ve);
    if (Object.keys(ve).length > 0) return;
    setApiErr(null);
    mutation.mutate({
      plan_name: form.plan_name,
      duration_days: form.duration_days,
      devices_limit: form.devices_limit,
      count: form.count,
      valid_days: form.valid_days,
      allowed_locations: form.location
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      tag: form.tag.trim() || null,
      note: form.note.trim() || null,
    });
  }

  function handleClose() {
    setForm(DEFAULTS);
    setErrors({});
    setCreated(null);
    setApiErr(null);
    onClose();
  }

  if (created) {
    return (
      <Modal
        open={open}
        onClose={handleClose}
        title={`Generated ${created.created} codes`}
        size="lg"
        actions={
          <>
            <PillButton
              variant="secondary"
              onClick={() => {
                void navigator.clipboard.writeText(created.codes.join("\n"));
              }}
            >
              Copy all
            </PillButton>
            <PillButton variant="primary" onClick={handleClose}>
              Done
            </PillButton>
          </>
        }
      >
        <div className="space-y-3">
          <p className="rounded-md border border-warning/40 bg-warning/10 p-3 text-xs text-warning">
            Сохраните коды сейчас — повторно они не будут показаны.
          </p>
          <pre className="max-h-80 overflow-auto rounded-md bg-bg-base p-3 font-mono text-[12px] text-text-base">
            {created.codes.join("\n")}
          </pre>
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Create codes batch"
      size="md"
      actions={
        <>
          <PillButton variant="ghost" onClick={handleClose}>
            Cancel
          </PillButton>
          <PillButton
            variant="primary"
            onClick={handleSubmit}
            loading={mutation.isPending}
          >
            Generate
          </PillButton>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <FormField label="Plan name" error={errors.plan_name ?? null}>
          <Select
            value={form.plan_name}
            onChange={(e) => setForm({ ...form, plan_name: e.target.value })}
          >
            <option value="7d">7d</option>
            <option value="1m">1m</option>
            <option value="3m">3m</option>
            <option value="6m">6m</option>
            <option value="1y">1y</option>
          </Select>
        </FormField>
        <FormField label="Duration (days)" error={errors.duration_days ?? null}>
          <Input
            type="number"
            value={form.duration_days}
            onChange={(e) =>
              setForm({ ...form, duration_days: Number(e.target.value) })
            }
          />
        </FormField>
        <FormField label="Devices" error={errors.devices_limit ?? null}>
          <Input
            type="number"
            min={1}
            max={5}
            value={form.devices_limit}
            onChange={(e) =>
              setForm({ ...form, devices_limit: Number(e.target.value) })
            }
          />
        </FormField>
        <FormField label="Count" error={errors.count ?? null}>
          <Input
            type="number"
            min={1}
            max={500}
            value={form.count}
            onChange={(e) => setForm({ ...form, count: Number(e.target.value) })}
          />
        </FormField>
        <FormField label="Valid days" error={errors.valid_days ?? null}>
          <Input
            type="number"
            min={1}
            max={365}
            value={form.valid_days}
            onChange={(e) =>
              setForm({ ...form, valid_days: Number(e.target.value) })
            }
          />
        </FormField>
        <FormField label="Locations (comma)" error={errors.location ?? null}>
          <Input
            value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
          />
        </FormField>
        <FormField label="Tag (optional)">
          <Input
            value={form.tag}
            onChange={(e) => setForm({ ...form, tag: e.target.value })}
          />
        </FormField>
        <FormField label="Note (optional)">
          <Textarea
            rows={2}
            value={form.note}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
          />
        </FormField>
      </div>
      {apiErr && (
        <p className="mt-3 text-sm text-negative" role="alert">
          {apiErr}
        </p>
      )}
    </Modal>
  );
}
