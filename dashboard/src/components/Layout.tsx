import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { Check, Moon, Sun } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";
import { Toaster } from "sonner";
import { useAuditVerify, usePending } from "../api/hooks";
import { cn } from "./ui";

export const SECTIONS = [
  { to: "/inbox", label: "Inbox", title: <>Waiting on <em>you</em></>, lede: "Requests your agents can't do alone. Approve or deny here, or from Telegram and Slack." },
  { to: "/history", label: "History", title: <>Every <em>decision</em></>, lede: "What your agents asked for, who answered, and which rule handled it. Mark any automatic approval as wrong." },
  { to: "/rules", label: "Rules", title: <>Learned from <em>your yeses</em></>, lede: "Patterns in your own decisions, backtested against everything you've denied. Nothing runs until you accept it." },
  { to: "/hard-lines", label: "Hard lines", title: <>Always <em>ask</em></>, lede: "Conditions that always go to a person, whatever the rules say." },
  { to: "/insights", label: "Insights", title: <>Attention <em>saved</em></>, lede: "How much of the approval load your rules are carrying." },
  { to: "/audit", label: "Audit", title: <>Tamper-<em>evident</em></>, lede: "Each entry carries the hash of the one before it. Edit or delete anything and the chain breaks." },
] as const;

type Theme = "light" | "dark";
function useTheme(): [Theme, () => void] {
  const system = () => (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme as Theme) || system());
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    try { localStorage.setItem("yr-theme", next); } catch { /* storage blocked */ }
  };
  return [theme, toggle];
}

function ChainStatus() {
  const { data, isError } = useAuditVerify();
  const ok = data?.ok && !isError;
  return (
    <div className="flex items-center gap-2 whitespace-nowrap text-xs text-mfg" data-testid="chain-status">
      <span className={cn("size-[7px] rounded-full", ok ? "bg-live shadow-[0_0_0_3px_var(--live-bg)]" : "bg-bad shadow-[0_0_0_3px_var(--bad-bg)]")} />
      <span className="max-md:hidden">
        {isError ? "Engine offline" : !data ? "connecting…" : data.ok ? `Chain OK · ${data.entries.toLocaleString()} entries` : `Chain broken at #${data.first_bad_seq}`}
      </span>
    </div>
  );
}

export function Layout() {
  const [theme, toggle] = useTheme();
  const pending = usePending().data?.length ?? 0;
  const path = useRouterState({ select: (s) => s.location.pathname });
  const section = SECTIONS.find((s) => path.startsWith(s.to)) ?? SECTIONS[0];

  return (
    <>
      <header className="sticky top-0 z-10 border-b border-line bg-bg/80 backdrop-blur-md">
        <div className="mx-auto flex h-[60px] max-w-[76rem] items-center gap-5 px-5 sm:px-8 max-md:h-auto max-md:flex-wrap max-md:gap-3 max-md:py-3">
          <Link to="/inbox" className="flex items-center gap-2 text-[15px] font-semibold tracking-tight max-md:flex-1">
            <span className="grid size-[22px] place-items-center rounded-md bg-fg text-bg"><Check size={14} strokeWidth={3} /></span>
            Yesrule
          </Link>
          <nav aria-label="Sections" className="no-scrollbar flex min-w-0 flex-1 gap-0.5 overflow-x-auto max-md:order-3 max-md:basis-full">
            {SECTIONS.map((s) => {
              const active = s.to === section.to;
              return (
                <Link key={s.to} to={s.to} aria-current={active ? "page" : undefined}
                  className={cn("relative whitespace-nowrap rounded-full px-3 py-1.5 text-[13.5px] transition-colors", active ? "text-bg" : "text-mfg hover:text-fg")}>
                  {active && <motion.span layoutId="tab" className="absolute inset-0 -z-10 rounded-full bg-fg" transition={{ type: "spring", bounce: 0.15, duration: 0.45 }} />}
                  {s.label}
                  {s.to === "/inbox" && pending > 0 && (
                    <span className="ml-1.5 inline-grid h-[18px] min-w-[18px] place-items-center rounded-full bg-brand px-1.5 text-[11px] font-semibold text-brand-fg">{pending}</span>
                  )}
                </Link>
              );
            })}
          </nav>
          <ChainStatus />
          <button onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            className="grid size-8 cursor-pointer place-items-center rounded-full border border-line bg-card">
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
          </button>
        </div>
      </header>

      <section className="dots border-b border-line">
        <div className="mx-auto max-w-[76rem] px-5 pb-7 pt-10 sm:px-8">
          <div className="eyebrow">{section.label}</div>
          <motion.h1 key={section.to} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="mt-2 font-serif text-[clamp(2.2rem,5vw,3.4rem)] leading-none tracking-[-0.025em] [&_em]:text-brand">
            {section.title}
          </motion.h1>
          <p className="mt-3 max-w-[34rem] text-[14.5px] text-mfg">{section.lede}</p>
        </div>
      </section>

      <main id="view" className="mx-auto max-w-[76rem] px-5 pb-16 pt-7 sm:px-8">
        <Outlet />
      </main>
      <Toaster position="bottom-center" theme={theme} toastOptions={{ className: "!rounded-full !font-sans" }} />
    </>
  );
}

export function Stack({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-3.5">{children}</div>;
}
