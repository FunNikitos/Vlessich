/** Create node modal (superadmin). */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FormField,
  Input,
  Modal,
  PillButton,
  Select,
} from "@/components";
import { api, ApiError } from "@/lib/api";
import type { NodeStatus } from "@/lib/types";

interface Props {
  open: boolean;
  onClose: () => void;
}

const HOSTNAME_RE = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$/i;
const IPV4_RE = /^(\d{1,3}\.){3}\d{1,3}$/;

export function CreateNodeModal({ open, onClose }: Props) {
  const [hostname, setHostname] = useState("");
  const [ip, setIp] = useState("");
  const [provider, setProvider] = useState("");
  const [region, setRegion] = useState("");
  const [status, setStatus] = useState<NodeStatus>("HEALTHY");
  const [err, setErr] = useState<string | null>(null);

  const qc = useQueryClient();

  const mut = useMutation({
    mutationFn: () =>
      api.nodes.create({
        hostname: hostname.trim(),
        current_ip: ip.trim() || null,
        provider: provider.trim() || null,
        region: region.trim() || null,
        status,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["nodes"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      reset();
      onClose();
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Ошибка"),
  });

  function reset() {
    setHostname("");
    setIp("");
    setProvider("");
    setRegion("");
    setStatus("HEALTHY");
    setErr(null);
  }

  function close() {
    reset();
    onClose();
  }

  const hostnameValid = HOSTNAME_RE.test(hostname.trim());
  const ipValid = ip.trim() === "" || IPV4_RE.test(ip.trim());
  const canSubmit = hostnameValid && ipValid && !mut.isPending;

  return (
    <Modal
      open={open}
      onClose={close}
      title="Create node"
      actions={
        <>
          <PillButton variant="ghost" onClick={close} disabled={mut.isPending}>
            Cancel
          </PillButton>
          <PillButton
            variant="primary"
            onClick={() => mut.mutate()}
            disabled={!canSubmit}
            loading={mut.isPending}
          >
            Create
          </PillButton>
        </>
      }
    >
      <div className="space-y-4">
        <FormField
          label="Hostname"
          error={
            hostname && !hostnameValid ? "Невалидный hostname" : undefined
          }
        >
          <Input
            placeholder="fi-01.example.com"
            value={hostname}
            onChange={(e) => setHostname(e.target.value)}
            autoFocus
          />
        </FormField>
        <FormField
          label="Current IP"
          error={!ipValid ? "Невалидный IPv4" : undefined}
        >
          <Input
            placeholder="1.2.3.4"
            value={ip}
            onChange={(e) => setIp(e.target.value)}
          />
        </FormField>
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Provider">
            <Input
              placeholder="hetzner / ovh / ..."
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            />
          </FormField>
          <FormField label="Region">
            <Input
              placeholder="fi-hel"
              value={region}
              onChange={(e) => setRegion(e.target.value)}
            />
          </FormField>
        </div>
        <FormField label="Status">
          <Select
            value={status}
            onChange={(e) => setStatus(e.target.value as NodeStatus)}
          >
            <option value="HEALTHY">HEALTHY</option>
            <option value="MAINTENANCE">MAINTENANCE</option>
            <option value="BURNED">BURNED</option>
          </Select>
        </FormField>
        {err && <p className="text-xs text-negative">{err}</p>}
      </div>
    </Modal>
  );
}
