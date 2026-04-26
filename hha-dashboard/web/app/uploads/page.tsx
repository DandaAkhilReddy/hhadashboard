import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api-client";
import { UploadDropZone } from "./UploadDropZone";

export default async function UploadsPage() {
  // Initial list server-side so first paint is fast; client polls for updates after that
  const initialUploads = await api.listUploads().catch(() => []);

  return (
    <>
      <PageHeader
        title="Upload Files"
        subtitle={
          <>
            Drop anything &mdash; census PDFs, monthly finance Excel, clinical audit spreadsheets,
            HR exports. The pipeline routes by filename and extracts aggregates within 15 minutes.
            <br />
            <span className="text-xs text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded mt-1 inline-block">
              Dev mode: upload hits Azurite (local Blob emulator). Run{" "}
              <code className="text-[11px]">uv run python -m jobs.upload_ingest.main</code> to
              process manually.
            </span>
          </>
        }
      />

      <UploadDropZone initialUploads={initialUploads} />
    </>
  );
}
