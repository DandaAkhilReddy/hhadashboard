/**
 * Census-portal entry page.
 *
 * Server component. Fetches today's prefill from the portal API using the
 * forwarded `census_session` cookie. If the session is missing or invalid
 * we redirect to /census/login.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { CensusEntryForm, type PortalSite } from "./CensusEntryForm";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const COOKIE_NAME = "census_session";

interface PrefillPayload {
  entry_date: string;
  sites: PortalSite[];
}

export default async function CensusEntryPage() {
  const cookieStore = await cookies();
  const token = cookieStore.get(COOKIE_NAME)?.value;
  if (!token) {
    redirect("/census/login");
  }

  const res = await fetch(`${API_BASE}/api/v1/census-portal/sites`, {
    headers: { Cookie: `${COOKIE_NAME}=${token}` },
    cache: "no-store",
  });

  if (res.status === 401) {
    redirect("/census/login");
  }

  if (!res.ok) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Could not load facility list (status {res.status}). Please try signing in again.
      </div>
    );
  }

  const prefill = (await res.json()) as PrefillPayload;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">
          Today&apos;s census — {prefill.entry_date}
        </h1>
        <p className="text-sm text-slate-500">
          Type the patient count for each facility, then save all.
        </p>
      </div>
      <CensusEntryForm
        initialDate={prefill.entry_date}
        initialSites={prefill.sites}
        apiBase={API_BASE}
      />
    </div>
  );
}
