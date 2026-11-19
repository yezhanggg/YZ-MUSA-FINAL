// Test Site, Compare tab: the unit on screen under today's rules and under each bill that would change them.
//   1. One card per column with its answer (Today, then the bills, each marked "not law").
//   2. What changes: only the rules a bill changes, today's value next to the bill's, the bill's in violet.
//   3. The rules that stay the same, folded under one line.
// Read off lib/lot/compare.ts. Nothing here decides a rule.
import { useState } from "react";
import { ChevronDown, ExternalLink } from "lucide-react";
import { cx } from "../../lib/cx";
import {
  compareView,
  type CompareCol,
  type CompareRow,
} from "../../lib/lot/compare";
import { BILL_LINK } from "../../lib/lot/nextLinks";
import type { LotRecord, Scenario } from "../../lib/lot/types";
import { TYPE_TITLE } from "../../lib/lot/words";
import { ANSWER_ICON, ANSWER_LOOK, NotLaw, StateIcon } from "./Answer";
import type { LotResult } from "./useLotResult";

/** Column names and the line under them. Only Philadelphia has a local bill. */
const COL: Record<Scenario, { name: string; line: string }> = {
  today: { name: "Today", line: "Rules in force" },
  local_reform: { name: "Local Bill", line: "Bill 250042" },
  state_reform: { name: "State Bill", line: "HB 2186" },
};

/** The answer as a small pill in its colour: icon and one or two words. */
function AnswerPill({ col }: { col: CompareCol }) {
  const L = ANSWER_LOOK[col.answer];
  return (
    <span
      className={cx(
        "inline-flex max-w-full items-center gap-1.5 self-start rounded-full py-1 pl-1 pr-2.5 ring-1",
        L.box,
      )}
      data-answer={col.answer}
    >
      <span
        className={cx(
          "grid h-5 w-5 shrink-0 place-items-center rounded-full [&_svg]:h-3 [&_svg]:w-3",
          L.icon,
        )}
        aria-hidden
      >
        {ANSWER_ICON[col.answer]}
      </span>
      <span className={cx("text-small font-semibold leading-tight", L.title)}>
        {col.title}
      </span>
    </span>
  );
}

/** One card per column: which rules, the answer, its short line. */
function AnswerCards({ cols }: { cols: CompareCol[] }) {
  return (
    // Side by side when the panel has room (container query on the tab), stacked on a phone.
    <section
      aria-label="Answers"
      className={cx(
        "grid grid-cols-1 gap-2",
        cols.length === 2 ? "@[26rem]:grid-cols-2" : "@[34rem]:grid-cols-3",
      )}
    >
      {cols.map((c) => (
        <div
          key={c.scenario}
          className={cx(
            "flex min-w-0 flex-col gap-2 rounded-xl p-3 ring-1",
            c.scenario === "today"
              ? "bg-white ring-stone-200/80"
              : "bg-violet-50/40 ring-violet-200/70",
          )}
          data-col={c.scenario}
        >
          {/* Stacked (phone): the name and the answer on one line. Side by side: the answer under the name. */}
          <div
            className={cx(
              "flex items-start justify-between gap-2",
              cols.length === 2
                ? "@[26rem]:flex-col @[26rem]:justify-start"
                : "@[34rem]:flex-col @[34rem]:justify-start",
            )}
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                <h3 className="text-small font-semibold text-slate-900">
                  {COL[c.scenario].name}
                </h3>
                {c.scenario !== "today" && <NotLaw />}
              </div>
              <p className="text-[11px] text-slate-500">
                {COL[c.scenario].line}
              </p>
            </div>
            <AnswerPill col={c} />
          </div>
          <p className="text-caption leading-snug text-slate-600">{c.sub}</p>
        </div>
      ))}
    </section>
  );
}

/** Rows of rules, one column per scenario. `diff`: a bill's value that differs from today's is set off in violet. */
function RuleTable({
  cols,
  rows,
  label,
  diff,
}: {
  cols: CompareCol[];
  rows: CompareRow[];
  label: string;
  diff: boolean;
}) {
  return (
    <div className="overflow-hidden rounded-xl bg-white ring-1 ring-stone-200/80">
      <table
        aria-label={label}
        className="w-full table-fixed border-collapse text-[12.5px]"
      >
        <colgroup>
          <col className="w-[31%]" />
          {cols.map((c) => (
            <col key={c.scenario} />
          ))}
        </colgroup>
        <thead className="border-b border-stone-200 bg-stone-50/80">
          <tr>
            <th
              scope="col"
              className="px-3 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500"
            >
              Rule
            </th>
            {cols.map((c) => (
              <th
                key={c.scenario}
                scope="col"
                className="px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500"
              >
                {COL[c.scenario].name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-stone-100">
          {rows.map((r) => (
            <tr
              key={r.id}
              data-compare-row={r.id}
              data-changed={r.changed || undefined}
            >
              <th
                scope="row"
                className={cx(
                  "px-3 py-2 text-left align-top font-medium",
                  diff ? "text-slate-900" : "text-slate-500",
                )}
              >
                {r.name}
              </th>
              {r.cells.map((cell, k) => {
                const changed =
                  diff &&
                  k > 0 &&
                  (cell?.text !== r.cells[0]?.text ||
                    cell?.state !== r.cells[0]?.state);
                return (
                  <td key={cols[k].scenario} className="px-2 py-2 align-top">
                    {cell ? (
                      <span className="flex min-w-0 items-start gap-1.5">
                        <StateIcon state={cell.state} small />
                        <span
                          className={cx(
                            "min-w-0 break-words tnum",
                            changed
                              ? "-mx-1 -my-0.5 rounded-md bg-violet-100/70 px-1 py-0.5 font-semibold text-violet-900"
                              : diff
                                ? "text-slate-700"
                                : "text-slate-500",
                          )}
                        >
                          {cell.text}
                        </span>
                      </span>
                    ) : (
                      <span className="text-slate-400">None</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Compare({ lot, r }: { lot: LotRecord; r: LotResult }) {
  const v = compareView(lot, r.rows);
  const [allOpen, setAllOpen] = useState(false);
  const u = r.unit;
  const changed = v.rows.filter((x) => x.changed);
  const same = v.rows.filter((x) => !x.changed);
  const bills = v.cols.length > 1;
  return (
    <div className="@container space-y-4" data-compare>
      <p className="px-1 text-caption text-slate-500">
        The same unit in every column: {TYPE_TITLE[u.type]}, {u.width} x{" "}
        {u.depth} ft, {u.stories} {u.stories === 2 ? "stories" : "story"}.
      </p>

      <AnswerCards cols={v.cols} />

      {bills && (
        <section aria-label="What changes">
          <h3 className="mb-1.5 flex items-center gap-2 px-1 text-small font-semibold text-slate-900">
            What changes
            <span className="rounded-full bg-violet-100 px-1.5 text-[11px] font-semibold text-violet-800 tnum">
              {changed.length}
            </span>
          </h3>
          {changed.length ? (
            <RuleTable
              cols={v.cols}
              rows={changed}
              label="Rules a bill would change"
              diff
            />
          ) : (
            <p className="rounded-xl bg-white px-3 py-2.5 text-small text-slate-600 ring-1 ring-stone-200/80">
              No rule changes for this unit on this lot.
            </p>
          )}
        </section>
      )}

      {same.length > 0 && (
        <section aria-label="Same in every column">
          <button
            type="button"
            onClick={() => setAllOpen(!allOpen)}
            aria-expanded={allOpen}
            className="tap flex w-full items-center justify-between gap-2 rounded-xl px-1 py-1 text-left text-small font-semibold text-slate-600 hover:text-slate-900"
          >
            <span>
              {bills ? "Same in every column" : "Every rule"}{" "}
              <span className="font-normal text-slate-400">
                ({same.length})
              </span>
            </span>
            <ChevronDown
              className={cx(
                "h-4 w-4 shrink-0 text-slate-400 transition-transform",
                allOpen && "rotate-180",
              )}
              aria-hidden
            />
          </button>
          {allOpen && (
            <div className="mt-1.5">
              <RuleTable
                cols={v.cols}
                rows={same}
                label="Rules that stay the same"
                diff={false}
              />
            </div>
          )}
        </section>
      )}

      <div className="space-y-1 border-t border-stone-100 px-1 pt-3 text-caption text-slate-500">
        {!bills && <p>No bill on file would change the rules on this lot.</p>}
        <p>
          Bills are not law. HB 2186 passed the House and is in a Senate
          committee. A bill not passed by Nov 30, 2026 dies.
        </p>
        {v.local ? (
          <p>Bill 250042 is a Philadelphia City Council bill, in committee.</p>
        ) : (
          <p>No local bill is on file for this town.</p>
        )}
        <a
          href={BILL_LINK.url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 font-semibold text-violet-700 hover:text-violet-900"
        >
          {BILL_LINK.label} <ExternalLink className="h-3 w-3" aria-hidden />
        </a>
      </div>
    </div>
  );
}
