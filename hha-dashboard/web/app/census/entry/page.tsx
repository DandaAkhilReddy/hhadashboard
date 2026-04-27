/**
 * Census-portal entry page (Phase 1).
 *
 * Server component. Reads the optional `?date=` search param (defaults to
 * server-today). Validates the portal session by forwarding the
 * `census_session` cookie to /api/v1/census-portal/sites; redirects to
 * /census/login on 401. Then fetches the summary so totals are server-rendered
 * before first paint.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { CensusEntryForm, type PortalSite, type PortalSummary } from "./CensusEntryForm";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const COOKIE_NAME = "census_session";

interface PrefillPayload {
  entry_date: string;
  sites: PortalSite[];
}

function isValidDate(s: string | undefined): s is string {
  return typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s);
}

export default async function CensusEntryPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const cookieStore = await cookies();
  const token = cookieStore.get(COOKIE_NAME)?.value;
  if (!token) {
    redirect("/census/login");
  }

  const params = await searchParams;
  const dateParam = Array.isArray(params.date) ? params.date[0] : params.date;
  const dateQuery = isValidDate(dateParam) ? `?date=${dateParam}` : "";

  const cookieHeader = `${COOKIE_NAME}=${token}`;
  const [sitesRes, summaryRes] = await Promise.all([
    fetch(`${API_BASE}/api/v1/census-portal/sites${dateQuery}`, {
      headers: { Cookie: cookieHeader },
      cache: "no-store",
    }),
    fetch(`${API_BASE}/api/v1/census-portal/summary${dateQuery}`, {
      headers: { Cookie: cookieHeader },
      cache: "no-store",
    }),
  ]);

  if (sitesRes.status === 401 || summaryRes.status === 401) {
    redirect("/census/login");
  }

  if (!sitesRes.ok || !summaryRes.ok) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Could not load census data (sites: {sitesRes.status} · summary: {summaryRes.status}). Please
        try signing in again.
      </div>
    );
  }

  const prefill = (await sitesRes.json()) as PrefillPayload;
  const summary = (await summaryRes.json()) as PortalSummary;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Daily Census</h1>
        <p className="text-sm text-slate-500">
          Enter the patient count for each facility. Already-entered rows show with a checkmark and
          an Edit button.
        </p>
      </div>
      <CensusEntryForm
        initialDate={prefill.entry_date}
        initialSites={prefill.sites}
        initialSummary={summary}
        apiBase={API_BASE}
      />
    </div>
  );
}
