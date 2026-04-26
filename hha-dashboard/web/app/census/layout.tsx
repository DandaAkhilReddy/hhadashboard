/**
 * Census-only portal layout.
 *
 * Stripped down — no role badges, no dashboard nav. The root layout's
 * <main> wrapper still applies (max-w-[1600px], px-6, py-8); we let it.
 * What we override here is just the "feel": full-screen-ish centered card
 * for login, narrower content area for entry.
 *
 * The portal cookie (`census_session`) is independent of the dashboard's
 * `hha_session` cookie — see web/middleware.ts for the routing rule and
 * api/app/routers/census_portal.py for the auth contract.
 */
export default function CensusLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="-mx-6 -my-8 min-h-[calc(100vh-0px)] bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="mx-auto flex max-w-3xl items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-indigo-700 font-extrabold text-white">
              H
            </div>
            <div className="text-base font-semibold text-slate-900">HHA Census Entry</div>
          </div>
          <div className="text-xs uppercase tracking-wide text-slate-500">Entry-only portal</div>
        </div>
      </header>
      <div className="mx-auto max-w-3xl px-6 py-8">{children}</div>
    </div>
  );
}
