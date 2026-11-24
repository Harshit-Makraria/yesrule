import { motion } from "motion/react";
import { useInsights } from "../api/hooks";
import { ErrorState, Panel, Skeleton, cn, td, th } from "../components/ui";

function Stat({ value, unit, label, first }: { value: React.ReactNode; unit?: string; label: string; first?: boolean }) {
  return (
    <div className={cn("py-6 pr-6", !first && "border-line sm:border-l sm:pl-6 max-sm:border-t")}>
      <dd className="font-serif text-[2.8rem] italic leading-none">
        {value}{unit && <small className="text-[.5em] text-brand">{unit}</small>}
      </dd>
      <dt className="mt-2 text-[13px] text-mfg">{label}</dt>
    </div>
  );
}

export function Insights() {
  const { data: i, error, isPending } = useInsights();
  if (error) return <ErrorState error={error} />;
  if (isPending) return <Skeleton className="h-64" />;

  const agents = Object.entries(i.agents).sort((a, b) => b[1].requests - a[1].requests);
  const max = Math.max(1, ...agents.map(([, v]) => v.requests));

  return (
    <>
      <dl className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] border-y border-line">
        <Stat first value={i.total_requests.toLocaleString()} label="requests from your agents" />
        <Stat value={Math.round(i.automation_rate * 100)} unit="%" label="handled by your rules" />
        <Stat value={i.minutes_saved_estimate} unit="m" label="minutes of attention saved" />
        <Stat value={i.median_response_ms == null ? "–" : Math.round(i.median_response_ms / 1000)} unit="s" label="median human response" />
      </dl>

      <Panel className="mt-6 overflow-x-auto">
        <table className="w-full border-collapse text-[13.5px]">
          <thead>
            <tr><th className={th}>Agent</th><th className={th}>Volume</th><th className={cn(th, "text-right")}>Requests</th>
              <th className={cn(th, "text-right")}>Automatic</th><th className={cn(th, "text-right")}>Denied</th></tr>
          </thead>
          <tbody className="[&>tr:last-child>td]:border-b-0">
            {agents.map(([name, v]) => (
              <tr key={name}>
                <td className={td}>{name}</td>
                <td className={cn(td, "w-[35%]")}>
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                    <motion.div className="h-full bg-brand" initial={{ width: 0 }} animate={{ width: `${(v.requests / max) * 100}%` }}
                      transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }} />
                  </div>
                </td>
                <td className={cn(td, "text-right tabular-nums")}>{v.requests}</td>
                <td className={cn(td, "text-right tabular-nums")}>{v.auto}</td>
                <td className={cn(td, "text-right tabular-nums")}>{v.denied}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <p className="mt-3 font-mono text-[11.5px] text-subtle">
        Rules: {i.rules.active} active · {i.rules.proposed} proposed · {i.rules.paused} paused. Time saved assumes ~30s of attention per avoided prompt.
      </p>
    </>
  );
}
