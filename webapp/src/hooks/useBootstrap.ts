import useSWR from "swr";
import { api, type BootstrapResponse } from "@/lib/api";

const KEY = "/v1/webapp/bootstrap";

/** SWR-cached Mini-App bootstrap (user + subscription summary). */
export function useBootstrap() {
  return useSWR<BootstrapResponse>(KEY, () => api.bootstrap(), {
    revalidateOnFocus: true,
    dedupingInterval: 15000,
    keepPreviousData: true,
  });
}
