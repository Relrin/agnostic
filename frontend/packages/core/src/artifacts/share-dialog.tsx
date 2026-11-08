// Share an artefact: who may open the link and for how long, the link itself (shown once), and the links already
// made for this file, each revocable.
import {
  artifactsCreateShareMutation,
  artifactsListSharesOptions,
  artifactsListSharesQueryKey,
  artifactsRevokeShareMutation,
  describeError,
  type ShareOut,
} from "@agnostic/api";
import {
  Badge,
  Button,
  Callout,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  RadioCards,
  SegmentedControl,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Link2 } from "lucide-react";
import { useState } from "react";

import { formatRelative } from "../format";
import { withQueryFn } from "../query";
import { shareLink, type Artifact } from "./api";

const EXPIRY = [
  { value: "3600", label: "1 hour" },
  { value: "86400", label: "1 day" },
  { value: "604800", label: "7 days" },
  { value: "2592000", label: "30 days" },
] as const;

type Expiry = (typeof EXPIRY)[number]["value"];

function ShareRow({ share, onRevoke, busy }: { share: ShareOut; onRevoke: () => void; busy: boolean }) {
  const tone = share.state === "active" ? "success" : "muted";
  return (
    <li className="flex items-center gap-2 py-1.5 text-[12.5px]">
      <Badge tone={tone}>{share.state}</Badge>
      <span className="text-fg-secondary">
        {share.audience === "link" ? "Anyone with the link" : "Members"}
      </span>
      <span className="text-fg-muted">
        {share.state === "active"
          ? `expires ${formatRelative(share.expires_at)}`
          : formatRelative(share.revoked_at ?? share.expires_at)}
        {` · opened ${String(share.opened_count)}×`}
      </span>
      {share.state === "active" && (
        <Button variant="destructive-text" size="28" className="ml-auto" disabled={busy} onClick={onRevoke}>
          Revoke
        </Button>
      )}
    </li>
  );
}

export function ShareDialog({
  instance,
  artifact,
  open,
  onOpenChange,
}: {
  instance: string;
  artifact: Artifact;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const client = useQueryClient();
  const [audience, setAudience] = useState<"org" | "link">("org");
  const [expiry, setExpiry] = useState<Expiry>("86400");
  const [link, setLink] = useState<string>();
  const [copied, setCopied] = useState(false);
  const listOptions = { path: { instance }, query: { session_id: artifact.session_id } };
  const shares = useQuery({ ...withQueryFn(artifactsListSharesOptions(listOptions)), enabled: open });
  const refresh = () => client.invalidateQueries({ queryKey: artifactsListSharesQueryKey(listOptions) });
  const create = useMutation({
    ...artifactsCreateShareMutation(),
    onSuccess: (created) => {
      setLink(shareLink(created.path));
      setCopied(false);
      void refresh();
    },
  });
  const revoke = useMutation({
    ...artifactsRevokeShareMutation(),
    onSuccess: () => {
      toast("Link revoked. It stopped working.");
      void refresh();
    },
  });
  const forThisFile = (shares.data?.data ?? []).filter((share) => share.storage_key === artifact.storage_key);
  const publicLinks = shares.data?.public_links === true;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setLink(undefined);
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Share {artifact.filename}</DialogTitle>
          <DialogDescription>
            The link shows this file as it is now. Later versions the agent writes are new files with links of
            their own.
          </DialogDescription>
        </DialogHeader>
        {link ? (
          <div className="flex flex-col gap-2">
            <Callout tone="info" title="Link created">
              Copy it now: it is shown only once.
            </Callout>
            <div className="flex gap-2">
              <Input aria-label="Share link" readOnly value={link} className="font-mono text-[12px]" />
              <Button
                variant="outline"
                size="32"
                onClick={() => {
                  void navigator.clipboard.writeText(link).then(() => {
                    setCopied(true);
                  });
                }}
              >
                {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
          </div>
        ) : (
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              create.mutate({
                path: { instance },
                body: {
                  session_id: artifact.session_id,
                  storage_key: artifact.storage_key,
                  filename: artifact.filename,
                  audience,
                  ttl_seconds: Number(expiry),
                },
              });
            }}
          >
            <RadioCards
              legend="Who can open it"
              value={audience}
              onValueChange={setAudience}
              options={[
                {
                  value: "org",
                  label: "Members of the organization",
                  description: "They sign in to open it.",
                },
                ...(publicLinks
                  ? [
                      {
                        value: "link" as const,
                        label: "Anyone with the link",
                        description: "No sign-in. Share it only where you would share the file.",
                      },
                    ]
                  : []),
              ]}
            />
            <div className="flex flex-col gap-1.5">
              <span className="text-[12px] font-medium text-fg-muted">Expires after</span>
              <SegmentedControl
                label="Expires after"
                value={expiry}
                onValueChange={setExpiry}
                options={EXPIRY}
              />
            </div>
            {create.isError && (
              <p className="text-[12px] text-danger">{describeError(create.error).reason}</p>
            )}
            <DialogFooter>
              <Button type="submit" variant="primary" size="32" disabled={create.isPending}>
                <Link2 aria-hidden />
                Create link
              </Button>
            </DialogFooter>
          </form>
        )}
        {forThisFile.length > 0 && (
          <section aria-label="Links to this file" className="border-t border-border-subtle pt-3">
            <h3 className="text-[12px] font-semibold text-fg-muted">Links to this file</h3>
            <ul className="divide-y divide-divider-row">
              {forThisFile.map((share) => (
                <ShareRow
                  key={share.id}
                  share={share}
                  busy={revoke.isPending}
                  onRevoke={() => {
                    revoke.mutate({ path: { instance, share_id: share.id } });
                  }}
                />
              ))}
            </ul>
          </section>
        )}
      </DialogContent>
    </Dialog>
  );
}
