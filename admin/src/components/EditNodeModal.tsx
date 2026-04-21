/** Edit node modal: patch IP / region / status (superadmin). */
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FormField,
  Input,
  Modal,
  PillButton,
  Select,
} from "@/components";
import { api, ApiError } from "@/lib/api";
import type { NodeOut, NodeStatus } from "@/lib/types";

interface Props {
  node: NodeOut | null;
  onClose: () => void;
}

const IPV4_RE = /^(\d{1,3}\.){3}\d{1,3}$/;

export function EditNodeModal({ node, onClose }: Props) {
  const [ip, setIp] = useState("");
  const [region, setRegion] = useState("");
  const [status, setStatus] = useState<NodeStatus>("HEALTHY");
  const [err, setErr] = useState<string | null>(null);

  const qc = useQueryClient();

  useEffect(() => {
    if (node) {
      setIp(node.current_ip ?? "");
      setRegion(node.region ?? "");
      setStatus(node.status);
      setErr(null);
    }
  }, [node]);

  const mut = useMutation({
    mutationFn: () => {
      if (!node) throw new Error("no node");
      return api.nodes.patch(node.id, {
        current_ip: ip.trim() === "" ? null : ip.trim(),
        region: region.trim() === "" ? null : region.trim(),
        status,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["nodes"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      if (node) qc.invalidateQueries({ queryKey: ["node-health", node.id] });
      onClose();
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : "Ошибка"),
  });

  const ipValid = ip.trim() === "" || IPV4_RE.test(ip.trim());
  const canSubmit = ipValid && !mut.isPending;

  return (
    <Modal
      open={node !== null}
      onClose={onClose}
      title={node ? `Edit · ${node.hostname}` : ""}
      actions={
        <>
          <PillButton variant="ghost" onClick={onClose} disabled={mut.isPending}>
            Cancel
          </PillButton>
          <PillButton
            variant="primary"
            onClick={() => mut.mutate()}
            disabled={!canSubmit}
            loading={mut.isPending}
          >
            Save
          </PillButton>
        </>
      }
    >
      <div className="space-y-4">
        <FormField
          label="Current IP"
          error={!ipValid ? "Невалидный IPv4" : undefined}
        >
          <Input
            value={ip}
            onChange={(e) => setIp(e.target.value)}
            placeholder="1.2.3.4"
          />
        </FormField>
        <FormField label="Region">
          <Input
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            placeholder="fi-hel"
          />
        </FormField>
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
