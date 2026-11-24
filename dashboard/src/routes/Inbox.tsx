import { AnimatePresence } from "motion/react";
import { useDecide, usePendingDetails } from "../api/hooks";
import type { RequestDetail } from "../api/types";
import { Stack } from "../components/Layout";
import { Button, Card, Empty, ErrorState, Risk, Skeleton, Status } from "../components/ui";
import { humanize, money, relative } from "../lib/format";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-bg px-3 py-2">
      <dt className="font-mono text-[11px] uppercase tracking-[0.06em] text-subtle">{label}</dt>
      <dd className="mt-0.5 font-medium [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

function RequestCard({ d }: { d: RequestDetail }) {
  const decide = useDecide();
  const p = d.payload;
  const ctx = p.context ?? {};
  const approvals = d.decisions.filter((x) => x.approved && x.human).length;

  return (
    <Card className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-6 gap-y-4 max-sm:grid-cols-1" data-req={d.id}>
      <div>
        <h3 className="text-[15px] font-medium tracking-tight">
          <b className="font-semibold">{d.agent}</b> wants to <b className="font-semibold">{humanize(d.action)}</b>
        </h3>
        <div className="mt-1 flex flex-wrap items-center gap-x-3.5 gap-y-1.5 text-[12.5px] text-subtle">
          <Risk band={d.risk_band} score={d.risk} />
          <span className="font-mono">{p.platform}</span>
          <span>asked {relative(d.created_at)}</span>
          <span>expires {relative(d.expires_at)}</span>
        </div>

        {ctx.command && (
          <pre className="mt-3.5 overflow-x-auto rounded-lg border border-ink-line bg-ink px-3.5 py-3 font-mono text-[12.5px] text-ink-fg">
            <span className="text-ink-muted">$ </span>{ctx.command}
          </pre>
        )}
        {ctx.summary && <p className="mt-3">{ctx.summary}</p>}

        <dl className="mt-3.5 grid grid-cols-2 gap-2.5 sm:grid-cols-[repeat(auto-fit,minmax(150px,1fr))]">
          {p.amount && <Fact label="Amount">{money(p.amount.value, p.amount.currency)}</Fact>}
          {p.recipient && <Fact label="Recipient">{p.recipient.id} {!p.recipient.known && <Status value="new" />}</Fact>}
          {d.client && <Fact label="Client">{d.client}</Fact>}
          <Fact label="Environment">{p.environment}</Fact>
          <Fact label="Reversible">{p.reversible ? "Yes" : <b>No</b>}</Fact>
          {d.approvals_needed > 1 && <Fact label="Approvals">{approvals} of {d.approvals_needed}</Fact>}
        </dl>

        <div className="mt-3.5 flex flex-wrap gap-1.5">
          {d.risk_reasons.map(([why, pts]) => (
            <span key={why} className="rounded-full border border-line bg-card px-2.5 py-0.5 text-xs text-mfg">
              {why} <b className="font-medium text-fg">+{pts}</b>
            </span>
          ))}
          <span className="rounded-full border border-line bg-card px-2.5 py-0.5 text-xs text-mfg">{d.reason}</span>
        </div>
      </div>

      <div className="flex min-w-[132px] flex-col gap-2 max-sm:flex-row [&>*]:max-sm:flex-1">
        <Button variant="primary" data-approve={d.id} disabled={decide.isPending}
          onClick={() => decide.mutate({ id: d.id, approved: true })}>Approve</Button>
        <Button variant="danger" data-deny={d.id} disabled={decide.isPending}
          onClick={() => decide.mutate({ id: d.id, approved: false })}>Deny</Button>
      </div>
    </Card>
  );
}

export function Inbox() {
  const { data, error, isPending } = usePendingDetails();
  if (error) return <ErrorState error={error} />;
  if (isPending) return <Stack><Skeleton /><Skeleton /></Stack>;
  if (!data.length) return <Empty title="All clear.">Nothing waiting. Your agents are either idle or covered by rules you've accepted.</Empty>;
  return (
    <Stack>
      <AnimatePresence mode="popLayout" initial={false}>
        {data.map((d) => <RequestCard key={d.id} d={d} />)}
      </AnimatePresence>
    </Stack>
  );
}
