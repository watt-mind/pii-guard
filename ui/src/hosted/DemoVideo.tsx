/*
 * The landing's slot for the 3-minute demo video (LAB-1499): a poster with a play button that
 * opens the video. It renders only when VITE_PII_GUARD_DEMO_VIDEO_URL is set at build time, so
 * no empty frame ships before the video exists. The poster is optional
 * (VITE_PII_GUARD_DEMO_VIDEO_POSTER); without it the slot draws its own.
 */
export function DemoVideo({ url, poster = import.meta.env.VITE_PII_GUARD_DEMO_VIDEO_POSTER || null }: { url: string; poster?: string | null }) {
  return (
    <a href={url} className="group relative block aspect-video max-h-[28rem] w-full overflow-hidden rounded-xl border border-line bg-surface-2" aria-label="Watch the 3-minute demo video (opens the video)">
      {poster ? <img src={poster} alt="" loading="lazy" decoding="async" className="absolute inset-0 size-full object-cover" /> : (
        <div aria-hidden="true" className="absolute inset-0 grid place-content-center gap-2 p-6 text-center">
          <p className="font-mono text-xs text-guard">3-minute demo</p>
          <p className="text-xl font-medium text-ink sm:text-2xl">A coding agent, real files, no real names sent</p>
        </div>
      )}
      <span aria-hidden="true" className="absolute bottom-4 left-4 inline-flex items-center gap-2 rounded-full bg-ink px-4 py-2 text-sm font-medium text-canvas shadow-sm group-hover:opacity-90">
        <svg viewBox="0 0 16 16" className="size-3.5 fill-current"><path d="M4 2.5v11l9-5.5z" /></svg>Watch the demo · 3 min
      </span>
    </a>
  );
}
