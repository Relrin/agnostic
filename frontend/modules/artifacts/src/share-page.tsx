import { artifactsSharedArtifactOptions, describeError, isProblem } from "@agnostic/api";
import {
  ArtifactPreview,
  downloadUrl,
  formatBytes,
  formatRelative,
  sharedContentUrl,
  withQueryFn,
} from "@agnostic/core";
import { Button, Callout, EmptyState, LoadingRows } from "@agnostic/ui";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { Download, ExternalLink } from "lucide-react";

const UNAUTHENTICATED = 401;

/** `/s/:token`: a shared file, read-only. Members' links need a sign-in; links for anyone don't. */
export function SharePage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const token = params.token ?? "";
  const shared = useQuery({
    ...withQueryFn(artifactsSharedArtifactOptions({ path: { token } })),
    retry: false,
  });

  let body;
  if (shared.isPending) body = <LoadingRows rows={4} label="Opening the shared file" />;
  else if (shared.isError) {
    const needsSignIn = isProblem(shared.error) && shared.error.status === UNAUTHENTICATED;
    body = needsSignIn ? (
      <EmptyState title="Sign in to open this file">
        It is shared with members of the organization.{" "}
        <Link to="/login" search={{ next: `/s/${token}` }} className="text-info hover:underline">
          Sign in
        </Link>
      </EmptyState>
    ) : (
      <Callout tone="danger" title="This link doesn't open">
        {describeError(shared.error).reason}
      </Callout>
    );
  } else {
    const file = shared.data;
    body = (
      <>
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <h1 className="text-[20px] font-semibold">{file.filename}</h1>
            <p className="text-[12.5px] text-fg-muted">
              Shared by {file.shared_by} · {formatBytes(file.size)} · link expires{" "}
              {formatRelative(file.expires_at)}
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="32"
              onClick={() => {
                downloadUrl(sharedContentUrl(token, "attachment"), file.filename);
              }}
            >
              <Download aria-hidden />
              Download
            </Button>
            <Button asChild variant="ghost" size="32">
              <a href={sharedContentUrl(token)} target="_blank" rel="noreferrer noopener">
                <ExternalLink aria-hidden />
                Open
              </a>
            </Button>
          </div>
        </header>
        <ArtifactPreview
          source={{
            url: sharedContentUrl(token),
            filename: file.filename,
            contentType: file.content_type,
            size: file.size,
          }}
        />
      </>
    );
  }

  return (
    <main className="min-h-screen bg-bg text-fg">
      <div className="mx-auto flex max-w-5xl flex-col gap-4 px-6 py-8">
        <span className="text-[12px] font-medium tracking-wide text-fg-muted uppercase">Shared file</span>
        {body}
      </div>
    </main>
  );
}
