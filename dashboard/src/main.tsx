import "./styles.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRootRoute, createRoute, createRouter, lazyRouteComponent, redirect, RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Layout } from "./components/Layout";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 2_000, retry: 1, refetchOnWindowFocus: true } },
});

const root = createRootRoute({ component: Layout });
// Each page is its own chunk, loaded on first visit (and preloaded on link hover).
const page = (path: string, load: () => Promise<Record<string, () => React.ReactNode>>, name: string) =>
  createRoute({ getParentRoute: () => root, path, component: lazyRouteComponent(load, name) });

const routeTree = root.addChildren([
  createRoute({ getParentRoute: () => root, path: "/", beforeLoad: () => { throw redirect({ to: "/inbox" }); } }),
  page("/inbox", () => import("./routes/Inbox"), "Inbox"),
  page("/history", () => import("./routes/History"), "History"),
  page("/rules", () => import("./routes/Rules"), "Rules"),
  page("/hard-lines", () => import("./routes/HardLines"), "HardLines"),
  page("/insights", () => import("./routes/Insights"), "Insights"),
  page("/audit", () => import("./routes/Audit"), "Audit"),
]);

const router = createRouter({ routeTree, defaultPreload: "intent" });
declare module "@tanstack/react-router" {
  interface Register { router: typeof router }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
