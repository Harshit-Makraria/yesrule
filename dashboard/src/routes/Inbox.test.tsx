import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RequestDetail } from "../api/types";
import { Inbox } from "./Inbox";

const detail: RequestDetail = {
  id: "req_1", agent: "claude-code", platform: "claude_code", action: "bash", status: "pending",
  risk: 70, risk_band: "high", client: null, amount: null, reason: "high risk: always asks",
  rule_id: null, created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 6e5).toISOString(),
  payload: { agent: "claude-code", platform: "claude_code", action: "bash", environment: "production",
    reversible: false, context: { command: "git push --force origin main" } },
  risk_reasons: [["irreversible", 30], ["production", 20]],
  receipt: null, approvals_needed: 2, decisions: [],
};

function mockEngine(pending: RequestDetail[]) {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: Request) => {
    const url = new URL(input.url).pathname + new URL(input.url).search;
    const body = input.method === "POST" ? await input.clone().json() : undefined;
    calls.push({ url, method: input.method, body });
    const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
    if (url.startsWith("/v1/requests?status=pending")) return json(pending);
    if (url.endsWith("/detail")) return json(pending.find((p) => url.includes(p.id)));
    if (url.endsWith("/decision")) {
      pending = pending.filter((p) => !url.includes(p.id));
      return json({ id: "req_1", status: "denied", approvals_so_far: 0, approvals_needed: 2 });
    }
    return json({ detail: "unexpected" }, 500);
  }));
  return calls;
}

function renderInbox() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Inbox /></QueryClientProvider>);
}

afterEach(() => vi.unstubAllGlobals());

it("renders a pending request with command, risk reasons and multi-approval progress", async () => {
  mockEngine([detail]);
  renderInbox();
  expect(await screen.findByText("git push --force origin main")).toBeInTheDocument();
  expect(screen.getByText("high · 70")).toBeInTheDocument();
  expect(screen.getByText("irreversible")).toBeInTheDocument();
  expect(screen.getByText("0 of 2")).toBeInTheDocument();
});

it("deny posts the decision and removes the card", async () => {
  const calls = mockEngine([detail]);
  renderInbox();
  await userEvent.click(await screen.findByRole("button", { name: "Deny" }));
  await waitFor(() => expect(screen.getByText("All clear.")).toBeInTheDocument());
  const post = calls.find((c) => c.method === "POST");
  expect(post).toMatchObject({ url: "/v1/requests/req_1/decision", body: { approved: false, by: "owner", channel: "web" } });
});

it("shows the empty state when nothing is waiting", async () => {
  mockEngine([]);
  renderInbox();
  expect(await screen.findByText("All clear.")).toBeInTheDocument();
});

it("explains when the engine is unreachable", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "boom" }), { status: 500 })));
  renderInbox();
  expect(await screen.findByText("Can't reach the engine.")).toBeInTheDocument();
  expect(screen.getByText(/boom/)).toBeInTheDocument();
});
