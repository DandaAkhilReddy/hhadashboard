import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api-client";
import { MonthlyFinanceForm } from "./MonthlyFinanceForm";

function defaultPeriod(): { year: number; month: number } {
  const now = new Date();
  // Default to last completed month
  const month = now.getMonth() === 0 ? 12 : now.getMonth();
  const year = now.getMonth() === 0 ? now.getFullYear() - 1 : now.getFullYear();
  return { year, month };
}

export default async function MonthlyFinancePage({
  searchParams,
}: {
  searchParams: Promise<{ year?: string; month?: string }>;
}) {
  const params = await searchParams;
  const { year: defaultYear, month: defaultMonth } = defaultPeriod();
  const year = params.year ? Number.parseInt(params.year, 10) : defaultYear;
  const month = params.month ? Number.parseInt(params.month, 10) : defaultMonth;

  const rows = await api.getMonthlyFinance(year, month).catch(() => []);

  return (
    <>
      <PageHeader
        title="Monthly Finance Entry"
        subtitle={
          <>
            Sandy Collins / Maribel Reyes — owner_finance.
            <br />
            <span className="text-xs text-slate-500">
              Enter FL (Ventra fallback) and TX (HHA manual) collections + AR + KPIs for the
              selected month. Re-saving overwrites in place. Finance board reflects immediately.
            </span>
          </>
        }
      />
      <MonthlyFinanceForm initialYear={year} initialMonth={month} initialRows={rows} />
    </>
  );
}
