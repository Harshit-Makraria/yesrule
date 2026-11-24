import { useMemo, useState } from "react";
import { useFlag, useHistory } from "../api/hooks";
import { Button, Empty, ErrorState, Panel, Risk, Skeleton, Status, cn, td, th } from "../components/ui";
import { humanize, money, relative } from "../lib/format";

const FILTERS = [
  { key: "all", label: "All", match: () => true },
  { key: "auto", label: "Automatic", match: (s: string) => s.startsWith("auto_") },
  { key: "human", label: "By a person", match: (s: string) => s === "approved" || s === "denied" },
  { key: "flagged", label: "Flagged", match: (s: string) => s === "flagged" },
] as const;

export function History() {
  const { data, error, isPending } = useHistory();
  const flag = useFlag();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const rows = useMemo(() => {
    const f = FILTERS.find((x) => x.key === filter)!;
    return (data ?? []).filter((r) => f.match(r.status));
  }, [data, filter]);

  if (error) return <ErrorState error={error} />;
  if (isPending) return <Skeleton className="h-96" />;
  if (!data.length) return <Empty title="No decisions yet.">Once your agents start asking, every answer lands here.</Empty>;

  return (
    <>
      <div role="group" aria-label="Filter" className="mb-4 inline-flex rounded-full border border-line bg-card p-[3px]">
        {FILTERS.map((f) => (
          <button key={f.key} aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}
            className={cn("cursor-pointer rounded-full px-3 py-1 text-[12.5px]", filter === f.key ? "bg-fg text-bg" : "text-mfg")}>
            {f.label}
          </button>
        ))}
      </div>
      <Panel className="overflow-x-auto">
        <table className="w-full border-collapse text-[13.5px]">
          <thead>
            <tr>
              <th className={th}>When</th><th className={th}>Agent</th><th className={th}>Action</th><th className={th}>Client</th>
              <th className={cn(th, "text-right")}>Amount</th><th className={th}>Risk</th><th className={th}>Result</th><th className={th} />
            </tr>
          </thead>
          <tbody className="[&>tr:last-child>td]:border-b-0">
            {rows.map((r) => (
              <tr key={r.id} className="transition-colors hover:bg-muted/45">
                <td className={cn(td, "font-mono text-subtle")}>{relative(r.created_at)}</td>
                <td className={td}>{r.agent}</td>
                <td className={td}>{humanize(r.action)}</td>
                <td className={td}>{r.client ?? "—"}</td>
                <td className={cn(td, "text-right tabular-nums")}>{money(r.amount) || "—"}</td>
                <td className={td}><Risk band={r.risk_band} score={r.risk} /></td>
                <td className={td}>
                  <Status value={r.status} />
                  {r.rule_id && <span className="ml-1.5 font-mono text-[11.5px] text-subtle">via {r.rule_id}</span>}
                </td>
                <td className={cn(td, "text-right")}>
                  {r.status === "auto_approved" && (
                    <Button size="sm" variant="danger" data-flag={r.id} disabled={flag.isPending} onClick={() => flag.mutate(r.id)}
                      title="This automatic approval was wrong: pause the rule">Wrong</Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
