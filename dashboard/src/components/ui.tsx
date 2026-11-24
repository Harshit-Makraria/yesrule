import { clsx } from "clsx";
import { motion } from "motion/react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Condition, RiskBand } from "../api/types";
import { humanize } from "../lib/format";

export const cn = clsx;

type Variant = "default" | "primary" | "brand" | "danger";
export function Button({
  variant = "default", size = "md", className, ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  return (
    <button
      {...props}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-full border font-medium transition-[transform,background-color,border-color] duration-200 ease-out-soft active:scale-[.97] disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
        size === "sm" ? "px-3 py-1 text-[12.5px]" : "px-4 py-2 text-[13.5px]",
        variant === "default" && "border-line bg-card hover:border-input",
        variant === "primary" && "border-fg bg-fg text-bg",
        variant === "brand" && "border-brand bg-brand text-brand-fg",
        variant === "danger" && "border-line bg-card text-bad hover:border-transparent hover:bg-bad-bg",
        className,
      )}
    />
  );
}

export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & Record<`data-${string}`, string>) {
  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: 24, transition: { duration: 0.2 } }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      className={cn("rounded-xl border border-line bg-card px-5 py-[1.15rem] shadow-card", className)}
      {...rest}
    >
      {children}
    </motion.article>
  );
}

export function Panel({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("rounded-xl border border-line bg-card shadow-card", className)}>{children}</div>;
}

const riskTone: Record<RiskBand, string> = {
  low: "text-live bg-live-bg",
  medium: "text-warn bg-warn-bg",
  high: "text-bad bg-bad-bg",
};
export function Risk({ band, score }: { band: RiskBand; score: number }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-xs font-medium", riskTone[band])}>
      <span className="size-1.5 rounded-full bg-current" />
      {band} · {score}
    </span>
  );
}

const statusTone: Record<string, string> = {
  approved: "text-live bg-live-bg", auto_approved: "text-live bg-live-bg", active: "text-live bg-live-bg",
  denied: "text-bad bg-bad-bg", auto_denied: "text-bad bg-bad-bg", flagged: "text-bad bg-bad-bg", expired: "text-bad bg-bad-bg",
  proposed: "text-brand bg-brand-bg", pending: "text-brand bg-brand-bg", new: "text-brand bg-brand-bg",
  paused: "text-warn bg-warn-bg",
};
export function Status({ value }: { value: string }) {
  return (
    <span className={cn("whitespace-nowrap rounded-md px-1.5 py-0.5 text-xs font-medium", statusTone[value] ?? "text-mfg bg-muted")}>
      {humanize(value)}
    </span>
  );
}

export function Cond({ c }: { c: Condition }) {
  return (
    <span className="rounded-md border border-line bg-bg px-2 py-0.5 font-mono text-[11.5px]">
      {c.field} <span className="text-brand">{c.op}</span> {JSON.stringify(c.value)}
    </span>
  );
}

export function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-input bg-card/60 px-6 py-14 text-center">
      <div className="font-serif text-[2rem] italic leading-tight tracking-tight">{title}</div>
      <p className="mx-auto mt-2 max-w-md text-mfg">{children}</p>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("h-28 animate-pulse rounded-xl bg-muted", className)} />;
}

export function ErrorState({ error }: { error: Error }) {
  return (
    <Empty title="Can't reach the engine.">
      {error.message}. Start it with <span className="font-mono">yesrule serve</span>.
    </Empty>
  );
}

export const th = "whitespace-nowrap border-b border-line px-5 py-3 text-left font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-subtle";
export const td = "whitespace-nowrap border-b border-line px-5 py-3 align-middle";
