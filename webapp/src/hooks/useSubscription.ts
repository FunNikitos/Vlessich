import useSWR from "swr";
import { api, type SubscriptionResponse } from "@/lib/api";

export const SUBSCRIPTION_KEY = "/v1/webapp/subscription";

/** SWR hook for full subscription details (urls + devices). */
export function useSubscription() {
  return useSWR<SubscriptionResponse>(
    SUBSCRIPTION_KEY,
    () => api.subscription(),
    {
      revalidateOnFocus: true,
      dedupingInterval: 30000,
      keepPreviousData: true,
    },
  );
}
