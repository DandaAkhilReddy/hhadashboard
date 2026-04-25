import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api-client";
import { DailyCensusForm } from "./DailyCensusForm";

export default async function DailyCensusPage() {
  // Server-side fetch of today's rows (may have existing values if Crystal
  // has already saved today or the cron processed a PDF earlier).
  // Catch errors so the form still renders — the client will show an inline
  // error if the POST later fails.
  const rows = await api.getDailyCensus().catch(() => []);

  return (
    <>
      <PageHeader
        title="Enter Today's Census"
        subtitle={
          <>
            Type the current inpatient census for each site. One row per site, one save.
            <br />
            <span className="text-xs text-slate-500">
              Re-saving the same day overwrites the previous value (idempotent). The Operations
              board updates immediately on save.
            </span>
          </>
        }
      />
      <DailyCensusForm initialRows={rows} />
    </>
  );
}
