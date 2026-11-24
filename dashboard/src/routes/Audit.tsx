import { useAudit, useAuditVerify } from "../api/hooks";
import { ErrorState, Panel, Skeleton, Status, cn, td, th } from "../components/ui";

export function Audit() {
  const verify = useAuditVerify();
  const entries = useAudit();
  const error = verify.error ?? entries.error;
  if (error) return <ErrorState error={error} />;
  if (!verify.data || !entries.data) return <Skeleton className="h-64" />;
  const v = verify.data;

  return (
    <>
      <div className="dots relative overflow-hidden rounded-xl bg-ink px-6 py-5 text-ink-fg shadow-float">
        <div className="eyebrow !text-ink-muted">{v.ok ? "Verified" : "Integrity failure"}</div>
        <h2 className="mt-2 font-serif text-[1.9rem] leading-tight tracking-tight">
          {v.ok ? "Hash chain verified" : `Chain broken at entry #${v.first_bad_seq}`}
        </h2>
        <p className="mt-2 max-w-[40rem] text-ink-muted">
          {v.entries.toLocaleString()} entries, each sealed with SHA-256 over its content and the previous hash. Run{" "}
          <span className="font-mono">yesrule audit verify</span> to check from the terminal.
        </p>
      </div>

      <Panel className="mt-4 overflow-x-auto">
        <table className="w-full border-collapse text-[13.5px]">
          <thead><tr><th className={cn(th, "text-right")}>#</th><th className={th}>Event</th><th className={th}>Data</th><th className={th}>Hash</th></tr></thead>
          <tbody className="[&>tr:last-child>td]:border-b-0">
            {entries.data.map((e) => (
              <tr key={e.seq}>
                <td className={cn(td, "text-right font-mono tabular-nums")}>{e.seq}</td>
                <td className={td}><Status value={e.event.replace("rule_", "rule ")} /></td>
                <td className={cn(td, "max-w-[420px] overflow-hidden text-ellipsis font-mono text-xs text-mfg")} title={JSON.stringify(e.data)}>
                  {JSON.stringify(e.data)}
                </td>
                <td className={cn(td, "font-mono text-[11.5px] text-subtle")}>{e.hash.slice(0, 10)} ↳</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
