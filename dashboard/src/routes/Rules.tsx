import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { Fragment, useState } from "react";
import { keys, useBacktest, useMine, useRuleAction, useRules } from "../api/hooks";
import type { Backtest, Rule } from "../api/types";
import { Stack } from "../components/Layout";
import { Button, Card, Cond, Empty, ErrorState, Skeleton, Status, cn } from "../components/ui";

const ORDER: Record<Rule["status"], number> = { proposed: 0, active: 1, paused: 2, expired: 3 };

function BacktestPanel({ bt }: { bt: Backtest }) {
  const items: [string, React.ReactNode][] = [
    ["Backtest", <b className={bt.passed ? "text-[#34d27b]" : "text-[#ff7a66]"}>{bt.passed ? "Passed" : "Failed"}</b>],
    ["History", `${bt.history_size} decisions`],
    ["Would auto-approve", bt.would_auto_approve],
    ["Past denials matched", bt.matched_past_denials],
  ];
  return (
    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }}
      className="mt-3 flex flex-wrap items-center gap-5 overflow-hidden rounded-lg bg-ink px-4 py-3 text-[13px] text-ink-fg" data-testid="backtest">
      {items.map(([k, v]) => (
        <div key={k}><div className="font-mono text-[11px] uppercase tracking-[0.06em] text-ink-muted">{k}</div>{v}</div>
      ))}
    </motion.div>
  );
}

function RuleCard({ r }: { r: Rule }) {
  const action = useRuleAction();
  const backtest = useBacktest();
  const { data: bt } = useQuery<Backtest>({ queryKey: keys.backtest(r.id), enabled: false });
  const e = r.evidence ?? {};
  const evidence: [React.ReactNode, string][] = [
    [e.approvals ?? "–", "approvals"],
    [e.denials ?? 0, "denials"],
    [e.days ?? "–", "days"],
    [e.wilson_lower_bound != null ? `${Math.round(e.wilson_lower_bound * 100)}%` : "–", "confidence"],
    [r.fire_count, "times fired"],
  ];
  const busy = action.isPending || backtest.isPending;

  return (
    <Card className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 max-sm:grid-cols-1" data-rule={r.id}>
      <div>
        <div className="flex items-center gap-1.5 font-mono text-xs text-subtle">
          {r.id} · <Status value={r.status} />{r.accepted_by && <> · accepted by {r.accepted_by}</>}
        </div>
        <h3 className="mt-1 text-base font-medium tracking-tight">{r.description}</h3>
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {r.conditions.map((c, i) => (
            <Fragment key={i}>{i > 0 && <span className="font-mono text-[11.5px] text-subtle">and</span>}<Cond c={c} /></Fragment>
          ))}
        </div>
        <div className="mt-3.5 grid grid-cols-[repeat(auto-fit,minmax(110px,1fr))] gap-px overflow-hidden rounded-lg border border-line bg-line">
          {evidence.map(([v, label]) => (
            <div key={label} className="bg-card px-3 py-2">
              <b className="block font-serif text-[1.6rem] font-normal italic leading-tight">{v}</b>
              <span className="text-[11.5px] text-subtle">{label}</span>
            </div>
          ))}
        </div>
        {bt && <BacktestPanel bt={bt} />}
      </div>
      <div className="flex min-w-[120px] flex-col gap-2 max-sm:flex-row max-sm:flex-wrap">
        {r.status === "active"
          ? <Button data-pause={r.id} disabled={busy} onClick={() => action.mutate({ id: r.id, action: "pause" })}>Pause</Button>
          : <Button variant="primary" data-accept={r.id} disabled={busy} onClick={() => action.mutate({ id: r.id, action: "accept" })}>Accept</Button>}
        <Button data-backtest={r.id} disabled={busy} onClick={() => backtest.mutate(r.id)}>Backtest</Button>
        {r.status !== "expired" && (
          <Button variant="danger" data-dismiss={r.id} disabled={busy} onClick={() => action.mutate({ id: r.id, action: "dismiss" })}>Dismiss</Button>
        )}
      </div>
    </Card>
  );
}

export function Rules() {
  const { data, error, isPending } = useRules();
  const mine = useMine();
  const [conf, setConf] = useState(0.9);

  if (error) return <ErrorState error={error} />;
  const rules = [...(data ?? [])].sort((a, b) => ORDER[a.status] - ORDER[b.status]);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="Confidence" className="inline-flex rounded-full border border-line bg-card p-[3px]">
          {([[0.9, "Strict · 90%"], [0.8, "Suggest early · 80%"]] as const).map(([v, label]) => (
            <button key={v} aria-pressed={conf === v} onClick={() => setConf(v)}
              className={cn("cursor-pointer rounded-full px-3 py-1 text-[12.5px]", conf === v ? "bg-fg text-bg" : "text-mfg")}>{label}</button>
          ))}
        </div>
        <Button variant="brand" data-mine disabled={mine.isPending} onClick={() => mine.mutate(conf)}>
          {mine.isPending ? "Looking…" : "Find rules now"}
        </Button>
      </div>
      {isPending ? <Stack><Skeleton className="h-44" /><Skeleton className="h-44" /></Stack>
        : !rules.length ? <Empty title="No patterns yet.">Keep deciding. After enough consistent answers over a few days, Yesrule proposes a rule with its evidence.</Empty>
        : <Stack><AnimatePresence initial={false}>{rules.map((r) => <RuleCard key={r.id} r={r} />)}</AnimatePresence></Stack>}
    </>
  );
}
