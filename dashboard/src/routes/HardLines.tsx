import { AnimatePresence } from "motion/react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { useAddHardLine, useDeleteHardLine, useHardLines } from "../api/hooks";
import type { Op } from "../api/types";
import { Stack } from "../components/Layout";
import { Button, Card, Cond, Empty, ErrorState, Panel, Skeleton } from "../components/ui";
import { parseConditionValue } from "../lib/format";

const OPS: Op[] = ["eq", "ne", "gte", "lte", "in", "contains"];
const FIELDS = ["action", "platform", "environment", "client", "amount.value", "recipient.known", "reversible", "target.type"];
const input = "w-full min-w-0 rounded-lg border border-input bg-bg px-3 py-2 placeholder:text-subtle";

export function HardLines() {
  const { data, error, isPending } = useHardLines();
  const add = useAddHardLine();
  const del = useDeleteHardLine();
  const [form, setForm] = useState({ field: "", op: "gte" as Op, value: "", description: "" });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!form.field.trim() || !form.value.trim()) return void toast.error("Field and value are required");
    const value = parseConditionValue(form.value, form.op);
    add.mutate(
      {
        id: `H-${Date.now().toString(36)}`,
        description: form.description.trim() || `${form.field} ${form.op} ${JSON.stringify(value)}`,
        conditions: [{ field: form.field.trim(), op: form.op, value }],
      },
      { onSuccess: () => setForm({ field: "", op: "gte", value: "", description: "" }) },
    );
  };

  if (error) return <ErrorState error={error} />;
  return (
    <>
      <Panel className="px-5 py-[1.15rem]">
        <div className="eyebrow">New hard line</div>
        <form onSubmit={submit} className="mt-4 grid grid-cols-[1.3fr_.7fr_1fr_1.6fr_auto] gap-2 max-md:grid-cols-2 [&>button]:max-md:col-span-full">
          <input id="lf" list="fields" aria-label="Field" placeholder="field · amount.value" className={input}
            value={form.field} onChange={(e) => setForm({ ...form, field: e.target.value })} />
          <datalist id="fields">{FIELDS.map((f) => <option key={f} value={f} />)}</datalist>
          <select id="lo" aria-label="Operator" className={input} value={form.op} onChange={(e) => setForm({ ...form, op: e.target.value as Op })}>
            {OPS.map((o) => <option key={o}>{o}</option>)}
          </select>
          <input id="lv" aria-label="Value" placeholder="value · 100000" className={input}
            value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
          <input id="ld" aria-label="Description" placeholder="description" className={input}
            value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <Button variant="primary" type="submit" data-addline disabled={add.isPending}>Add line</Button>
        </form>
        <p className="mt-3 font-mono text-[11.5px] text-subtle">Fields: {FIELDS.join(", ")}</p>
      </Panel>

      <div className="mt-3.5">
        {isPending ? <Skeleton /> : !data.length ? (
          <Empty title="No hard lines.">Try <span className="font-mono">amount.value gte 100000</span> so large payments always reach you.</Empty>
        ) : (
          <Stack>
            <AnimatePresence initial={false}>
              {data.map((l) => (
                <Card key={l.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-4">
                  <div>
                    <div className="font-mono text-xs text-subtle">{l.id}</div>
                    <h3 className="mt-1 text-base font-medium tracking-tight">{l.description}</h3>
                    <div className="mt-3 flex flex-wrap gap-1.5">{l.conditions.map((c, i) => <Cond key={i} c={c} />)}</div>
                  </div>
                  <Button variant="danger" data-delline={l.id} onClick={() => del.mutate(l.id)}>Remove</Button>
                </Card>
              ))}
            </AnimatePresence>
          </Stack>
        )}
      </div>
    </>
  );
}
