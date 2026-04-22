import { SWRConfig } from "swr";
import { Route, Routes } from "react-router-dom";
import { HomePage } from "@/pages/Home";
import { SubscriptionPage } from "@/pages/Subscription";
import { RoutingPage } from "@/pages/Routing";
import { useTelegram } from "@/hooks/useTelegram";

export function App() {
  useTelegram();
  return (
    <SWRConfig
      value={{
        revalidateOnFocus: true,
        shouldRetryOnError: true,
        errorRetryCount: 3,
        errorRetryInterval: 2000,
      }}
    >
      <main className="mx-auto flex min-h-full w-full max-w-md flex-col gap-4 px-4 py-5">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/subscription" element={<SubscriptionPage />} />
          <Route path="/routing" element={<RoutingPage />} />
        </Routes>
      </main>
    </SWRConfig>
  );
}
