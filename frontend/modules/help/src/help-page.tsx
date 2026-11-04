// `/help/*`: the user guides the installation bundles (served by the API, so they work without internet access).
import {
  describeError,
  systemListGuidesOptions,
  systemReadGuideOptions,
  type GuideEntry,
} from "@agnostic/api";
import { resolveGuideLink, withQueryFn } from "@agnostic/core";
import { EmptyState, ErrorState, LoadingRows, MarkdownView, PageIntro } from "@agnostic/ui";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";

const SECTION_TITLES: Record<string, string> = {
  "": "Guides",
  admin: "Administration",
  runbooks: "Runbooks",
  security: "Security",
};

function sectionOf(path: string): string {
  return path.includes("/") ? (path.split("/")[0] ?? "") : "";
}

function GuideIndex({ guides }: { guides: readonly GuideEntry[] }) {
  const sections = new Map<string, GuideEntry[]>();
  for (const guide of guides) {
    const key = sectionOf(guide.path);
    sections.set(key, [...(sections.get(key) ?? []), guide]);
  }
  return (
    <div className="grid gap-6 md:grid-cols-2">
      {[...sections.entries()].map(([section, entries]) => (
        <section key={section || "guides"} className="flex flex-col gap-2">
          <h2 className="text-[14.5px] font-semibold">{SECTION_TITLES[section] ?? section}</h2>
          <ul className="flex flex-col gap-1.5 text-[13.5px]">
            {entries.map((guide) => (
              <li key={guide.path}>
                <Link to="/help/$" params={{ _splat: guide.path }} className="text-info hover:underline">
                  {guide.title}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function Guide({ path }: { path: string }) {
  const guide = useQuery(withQueryFn(systemReadGuideOptions({ path: { path } })));
  if (guide.isPending) return <LoadingRows rows={10} label="Loading the guide" />;
  if (guide.error) {
    return <ErrorState title="This guide didn't load" reason={describeError(guide.error).reason} />;
  }
  return (
    <article className="max-w-[860px]">
      <MarkdownView internalLink={(href) => resolveGuideLink(path, href)}>{String(guide.data)}</MarkdownView>
    </article>
  );
}

export function HelpPage() {
  // The app's router isn't registered for type inference in modules, so params are read loosely.
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const path = params._splat ?? "";
  const index = useQuery(withQueryFn(systemListGuidesOptions()));

  return (
    <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-6 px-8 pt-6 pb-10">
      <PageIntro
        title="Help"
        actions={
          path ? (
            <Link to="/help" className="text-[13px] text-info hover:underline">
              All guides
            </Link>
          ) : undefined
        }
      >
        The guides that came with this installation: installing and upgrading, sign-in, instances and keys,
        building in Studio, operating runs, and runbooks for when something breaks.
      </PageIntro>
      {path ? (
        <Guide path={path} />
      ) : index.isPending ? (
        <LoadingRows rows={6} label="Loading the guides" />
      ) : index.error ? (
        <ErrorState reason={describeError(index.error).reason} onRetry={() => void index.refetch()} />
      ) : !index.data.available || index.data.guides.length === 0 ? (
        <EmptyState title="No guides are bundled with this installation">
          The guides ship in the agnostic image. When running from source, set AGNOSTIC_HTTP__DOCS_DIR to the
          repository&apos;s docs/guides folder.
        </EmptyState>
      ) : (
        <GuideIndex guides={index.data.guides} />
      )}
    </div>
  );
}
