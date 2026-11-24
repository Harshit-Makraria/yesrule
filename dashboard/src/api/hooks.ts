import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, call } from "./client";
import type {
  AuditEntry, AuditVerify, Backtest, Condition, FlagResult, HardLine, Insights,
  RequestDetail, RequestOut, RequestSummary, Rule,
} from "./types";

export const keys = {
  pending: ["requests", "pending"] as const,
  pendingDetails: ["requests", "pending", "details"] as const,
  history: ["requests", "history"] as const,
  rules: ["rules"] as const,
  backtest: (id: string) => ["rules", id, "backtest"] as const,
  hardLines: ["hard-lines"] as const,
  auditVerify: ["audit", "verify"] as const,
  audit: ["audit", "entries"] as const,
  insights: ["insights"] as const,
};

/* ---------- queries ---------- */

export const usePending = () =>
  useQuery({
    queryKey: keys.pending,
    queryFn: () => call<RequestSummary[]>(api.GET("/v1/requests", { params: { query: { status: "pending" } } })),
    refetchInterval: 5_000,
  });

/** Pending requests with full detail (payload, reasons, multi-approval progress). */
export const usePendingDetails = () =>
  useQuery({
    queryKey: keys.pendingDetails,
    queryFn: async () => {
      const list = await call<RequestSummary[]>(api.GET("/v1/requests", { params: { query: { status: "pending" } } }));
      return Promise.all(list.map((r) =>
        call<RequestDetail>(api.GET("/v1/requests/{request_id}/detail", { params: { path: { request_id: r.id } } }))));
    },
    refetchInterval: 5_000,
  });

export const useHistory = () =>
  useQuery({
    queryKey: keys.history,
    queryFn: async () =>
      (await call<RequestSummary[]>(api.GET("/v1/requests", { params: { query: { limit: 300 } } })))
        .filter((r) => r.status !== "pending"),
  });

export const useRules = () =>
  useQuery({ queryKey: keys.rules, queryFn: () => call<Rule[]>(api.GET("/v1/rules")) });

export const useHardLines = () =>
  useQuery({ queryKey: keys.hardLines, queryFn: () => call<HardLine[]>(api.GET("/v1/hard-lines")) });

export const useAuditVerify = () =>
  useQuery({ queryKey: keys.auditVerify, queryFn: () => call<AuditVerify>(api.GET("/v1/audit/verify")), refetchInterval: 15_000 });

export const useAudit = () =>
  useQuery({ queryKey: keys.audit, queryFn: () => call<AuditEntry[]>(api.GET("/v1/audit", { params: { query: { limit: 200 } } })) });

export const useInsights = () =>
  useQuery({ queryKey: keys.insights, queryFn: () => call<Insights>(api.GET("/v1/insights")) });

/* ---------- mutations ---------- */

/** Anything that changes state can move requests, rules and the audit chain, so refresh them all. */
function useInvalidateAll() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}

const onError = (e: Error) => toast.error(e.message);

export function useDecide() {
  const qc = useQueryClient();
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, approved }: { id: string; approved: boolean }) =>
      call<RequestOut>(api.POST("/v1/requests/{request_id}/decision", {
        params: { path: { request_id: id } },
        body: { approved, by: "owner", channel: "web" },
      })),
    // Optimistic: the card leaves the inbox immediately; restored if the engine refuses.
    onMutate: async ({ id }) => {
      const snapshot: [QueryKey, unknown][] = [];
      for (const key of [keys.pending, keys.pendingDetails]) {
        await qc.cancelQueries({ queryKey: key, exact: true });
        snapshot.push([key, qc.getQueryData(key)]);
        qc.setQueryData<{ id: string }[]>(key, (old) => old?.filter((r) => r.id !== id));
      }
      return { snapshot };
    },
    onError: (e, _v, ctx) => {
      ctx?.snapshot.forEach(([k, v]) => qc.setQueryData(k, v));
      onError(e);
    },
    onSuccess: (r, { approved }) =>
      toast.success(r.status === "pending" ? `Recorded · ${r.approvals_so_far} of ${r.approvals_needed} approvals` : approved ? "Approved" : "Denied"),
    onSettled: invalidate,
  });
}

export function useFlag() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (id: string) =>
      call<FlagResult>(api.POST("/v1/requests/{request_id}/flag", { params: { path: { request_id: id } }, body: { by: "owner" } })),
    onSuccess: (r) => toast.success(r.rule_paused ? `Marked wrong · ${r.rule} paused` : "Marked wrong"),
    onError,
    onSettled: invalidate,
  });
}

export function useMine() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (minConfidence: number) =>
      call<Rule[]>(api.POST("/v1/rules/mine", { params: { query: { min_confidence: minConfidence } } })),
    onSuccess: (r) => toast.success(r.length ? `${r.length} new rule${r.length > 1 ? "s" : ""} proposed` : "No new patterns yet"),
    onError,
    onSettled: invalidate,
  });
}

export function useRuleAction() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "accept" | "pause" | "dismiss" }) =>
      call<{ id: string; status: string }>(api.POST("/v1/rules/{rule_id}/{action}", { params: { path: { rule_id: id, action } } })),
    onSuccess: (_r, { action }) => toast.success({ accept: "Rule active", pause: "Rule paused", dismiss: "Rule dismissed" }[action]),
    onError,
    onSettled: invalidate,
  });
}

export function useBacktest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      call<Backtest>(api.GET("/v1/rules/{rule_id}/backtest", { params: { path: { rule_id: id } } })),
    onSuccess: (bt) => qc.setQueryData(keys.backtest(bt.rule), bt),
    onError,
  });
}

export function useAddHardLine() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (line: { id: string; description: string; conditions: Condition[] }) =>
      call(api.POST("/v1/hard-lines", { body: line as never })),
    onSuccess: () => toast.success("Hard line added"),
    onError,
    onSettled: invalidate,
  });
}

export function useDeleteHardLine() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (id: string) => call(api.DELETE("/v1/hard-lines/{line_id}", { params: { path: { line_id: id } } })),
    onSuccess: () => toast.success("Hard line removed"),
    onError,
    onSettled: invalidate,
  });
}
