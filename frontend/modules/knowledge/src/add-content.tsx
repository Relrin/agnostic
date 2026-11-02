import { contextKnowledgeContentOptions, describeError, type KnowledgeBaseOut } from "@agnostic/api";
import { PermissionGate, formatBytes } from "@agnostic/core";
import {
  Button,
  Input,
  SegmentedControl,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  ThinBar,
  cn,
  toast,
} from "@agnostic/ui";
import { skipToken, useQuery, useQueryClient } from "@tanstack/react-query";
import { Folder, Plus, Upload, X } from "lucide-react";
import { useId, useRef, useState } from "react";

import {
  BASES_KEY,
  CONTENT_KEY,
  alreadyIndexed,
  uploadFile,
  useIngest,
  useRemoteFiles,
  useRemoteSources,
  type IngestCommon,
  type KnowledgeSettings,
} from "./knowledge-api";

type Tab = "file" | "url" | "text" | "remote";
const TABS: readonly { value: Tab; label: string }[] = [
  { value: "file", label: "File" },
  { value: "url", label: "URL" },
  { value: "text", label: "Text" },
  { value: "remote", label: "Remote" },
];
const AUTO = "auto";

/** "Add content" aside: four sources, then name, metadata, reader and chunker shared by all of them. */
export function AddContent({
  instance,
  base,
  settings,
}: {
  instance: string;
  base: KnowledgeBaseOut;
  settings: KnowledgeSettings | undefined;
}) {
  const ids = useId();
  const client = useQueryClient();
  const [tab, setTab] = useState<Tab>("file");
  const [files, setFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState<number | undefined>(undefined);
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const [metadata, setMetadata] = useState<{ key: string; value: string }[]>([]);
  const [reader, setReader] = useState(AUTO);
  const [chunker, setChunker] = useState(AUTO);
  const [skipExisting, setSkipExisting] = useState(true);
  const [source, setSource] = useState<string | undefined>(undefined);
  const [prefix, setPrefix] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const fileInput = useRef<HTMLInputElement>(null);
  const ingest = useIngest(instance, base.id);

  // Names already in the knowledge base (newest 100): "indexed" remote files and skipped uploads.
  const namesOptions = contextKnowledgeContentOptions({
    path: { instance },
    query: { knowledge_id: base.id, limit: 100 },
  });
  const names = useQuery({ ...namesOptions, queryFn: namesOptions.queryFn ?? skipToken });
  const known = new Set(
    (names.data?.data ?? []).flatMap((row) => (typeof row.name === "string" ? [row.name] : [])),
  );
  const sources = useRemoteSources(instance, tab === "remote" ? base.id : undefined);
  const sourceId = source ?? sources.data?.[0]?.id;
  const remote = useRemoteFiles(instance, base.id, tab === "remote" ? sourceId : undefined, prefix);

  const readers = Object.values(settings?.readers ?? {});
  const chunkers = Object.entries(settings?.chunkers ?? {});
  const common = (): IngestCommon => ({
    name,
    metadata: Object.fromEntries(
      metadata.filter((row) => row.key.trim()).map((row) => [row.key.trim(), row.value]),
    ),
    readerId: reader === AUTO ? undefined : reader,
    chunker: chunker === AUTO ? undefined : chunker,
  });
  const reset = () => {
    setFiles([]);
    setUrl("");
    setText("");
    setName("");
    setPicked(new Set());
    setProgress(undefined);
  };
  const done = (count: number) => {
    toast.success(
      `Added ${String(count)} ${count === 1 ? "item" : "items"} to ${base.name}; processing has started.`,
    );
    reset();
  };

  const uploadable = skipExisting ? files.filter((file) => !known.has(file.name)) : files;
  const remoteFiles = (remote.data?.files ?? []).map((file) => ({
    ...file,
    indexed: alreadyIndexed(known, { name: file.name, key: file.key }),
  }));
  const ready =
    (tab === "file" && uploadable.length > 0) ||
    (tab === "url" && /^https?:\/\//.test(url.trim())) ||
    (tab === "text" && text.trim().length > 0) ||
    (tab === "remote" && picked.size > 0);
  const busy = ingest.isPending || progress !== undefined;

  const submit = async () => {
    try {
      if (tab === "file") {
        for (const [index, file] of uploadable.entries()) {
          await uploadFile(
            instance,
            base.id,
            file,
            { ...common(), name: uploadable.length > 1 ? "" : name },
            (fraction) => {
              setProgress((index + fraction) / uploadable.length);
            },
          );
        }
        await client.invalidateQueries({ queryKey: CONTENT_KEY });
        await client.invalidateQueries({ queryKey: BASES_KEY });
        done(uploadable.length);
      } else if (tab === "url") {
        done(await ingest.mutateAsync({ kind: "url", url: url.trim(), common: common() }));
      } else if (tab === "text") {
        done(await ingest.mutateAsync({ kind: "text", text, common: common() }));
      } else if (sourceId) {
        done(await ingest.mutateAsync({ kind: "remote", sourceId, paths: [...picked], common: common() }));
      }
    } catch (error) {
      setProgress(undefined);
      toast.error(`Couldn't add content: ${describeError(error).reason}`);
    }
  };

  return (
    <aside
      aria-label="Add content"
      className="flex min-w-0 flex-[1_1_320px] flex-col border-l border-border-subtle bg-rail lg:max-w-[400px]"
    >
      <header className="flex flex-col gap-3 border-b border-border-subtle px-5 py-4">
        <h2 className="text-[14px] font-semibold">Add content</h2>
        <SegmentedControl label="Content source" value={tab} onValueChange={setTab} options={TABS} />
      </header>
      <PermissionGate
        scope="knowledge:write"
        instance={instance}
        fallback={
          <p className="px-5 py-4 text-[12.5px] text-fg-muted">
            Adding content needs <code className="font-mono">knowledge:write</code> on this instance.
          </p>
        }
      >
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-4">
          {tab === "file" && (
            <div className="flex flex-col gap-2">
              <button
                type="button"
                className="flex cursor-pointer flex-col items-center gap-1.5 rounded-card border border-dashed border-border-dashed px-4 py-6 text-center hover:bg-surface-hover"
                onClick={() => fileInput.current?.click()}
                onDragOver={(event) => {
                  event.preventDefault();
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  setFiles([...files, ...Array.from(event.dataTransfer.files)]);
                }}
              >
                <Upload className="size-5 text-fg-muted" aria-hidden />
                <span className="text-[13px]">
                  Drop files or <span className="text-info">browse</span>
                </span>
                <span className="text-[12px] text-fg-muted">PDF, DOCX, Markdown, CSV, JSON, TXT</span>
              </button>
              <input
                ref={fileInput}
                type="file"
                multiple
                hidden
                aria-label="Files to add"
                onChange={(event) => {
                  setFiles([...files, ...Array.from(event.target.files ?? [])]);
                  event.target.value = "";
                }}
              />
              {files.map((file) => (
                <div
                  key={`${file.name}:${String(file.size)}`}
                  className="flex items-center gap-2 text-[12.5px]"
                >
                  <span className="min-w-0 flex-1 truncate font-mono">{file.name}</span>
                  <span className="text-fg-muted">
                    {skipExisting && known.has(file.name)
                      ? "already added · skipped"
                      : formatBytes(file.size)}
                  </span>
                  <button
                    type="button"
                    aria-label={`Remove ${file.name}`}
                    className="cursor-pointer text-fg-muted hover:text-fg"
                    onClick={() => {
                      setFiles(files.filter((item) => item !== file));
                    }}
                  >
                    <X className="size-3.5" aria-hidden />
                  </button>
                </div>
              ))}
              {progress !== undefined && (
                <div className="flex flex-col gap-1" role="status" aria-label="Upload progress">
                  <ThinBar share={progress} />
                  <span className="text-[12px] text-fg-muted">Uploading… {Math.round(progress * 100)}%</span>
                </div>
              )}
            </div>
          )}
          {tab === "url" && (
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`${ids}-url`} className="text-[13px] font-medium text-fg-secondary">
                URL
              </label>
              <Input
                id={`${ids}-url`}
                placeholder="https://help.example.com/billing/"
                value={url}
                onChange={(event) => {
                  setUrl(event.target.value);
                }}
              />
              <span className="text-[12px] text-fg-muted">
                The website reader follows links on the same site as configured on the instance.
              </span>
            </div>
          )}
          {tab === "text" && (
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`${ids}-text`} className="text-[13px] font-medium text-fg-secondary">
                Text
              </label>
              <Textarea
                id={`${ids}-text`}
                rows={6}
                className="font-sans text-[13px]"
                placeholder="Paste text the agents should be able to cite"
                value={text}
                onChange={(event) => {
                  setText(event.target.value);
                }}
              />
            </div>
          )}
          {tab === "remote" && (
            <div className="flex flex-col gap-2.5">
              {sources.data?.length === 0 ? (
                <p className="text-[12.5px] text-fg-muted">
                  No remote sources are registered on this knowledge base (S3, GCS, GitHub or SharePoint).
                </p>
              ) : (
                <>
                  <Select
                    value={sourceId ?? ""}
                    onValueChange={(value) => {
                      setSource(value);
                      setPrefix("");
                      setPicked(new Set());
                    }}
                  >
                    <SelectTrigger aria-label="Source" className="h-8">
                      <SelectValue placeholder="Source" />
                    </SelectTrigger>
                    <SelectContent>
                      {(sources.data ?? []).map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.name} · {item.type}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input
                    aria-label="Prefix"
                    mono
                    placeholder="Prefix, e.g. macros/"
                    className="h-8"
                    value={prefix}
                    onChange={(event) => {
                      setPrefix(event.target.value);
                    }}
                  />
                  <ul aria-label={`Files in ${prefix || "/"}`} className="flex flex-col gap-1">
                    {(remote.data?.folders ?? []).map((folder) => (
                      <li key={folder.prefix}>
                        <button
                          type="button"
                          className="flex cursor-pointer items-center gap-2 font-mono text-[12.5px] text-fg-secondary hover:text-fg"
                          onClick={() => {
                            setPrefix(folder.prefix);
                          }}
                        >
                          <Folder className="size-3.5" aria-hidden />
                          {folder.name}/
                        </button>
                      </li>
                    ))}
                    {remoteFiles.map((file) => (
                      <li key={file.key}>
                        <label
                          className={cn(
                            "flex items-center gap-2 text-[12.5px]",
                            file.indexed && skipExisting ? "text-fg-disabled" : "text-fg",
                          )}
                        >
                          <input
                            type="checkbox"
                            disabled={file.indexed && skipExisting}
                            checked={picked.has(file.key)}
                            onChange={(event) => {
                              const next = new Set(picked);
                              if (event.target.checked) next.add(file.key);
                              else next.delete(file.key);
                              setPicked(next);
                            }}
                          />
                          <span className="min-w-0 flex-1 truncate font-mono">{file.name}</span>
                          <span className="text-fg-muted">
                            {file.indexed ? "indexed" : `${file.size ? formatBytes(file.size) : ""} · new`}
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                  <span className="text-[12px] text-fg-muted">
                    {picked.size} new {picked.size === 1 ? "file" : "files"} selected
                    {skipExisting ? " · already-indexed files are skipped" : ""}
                  </span>
                </>
              )}
            </div>
          )}

          <hr className="border-border-subtle" />
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${ids}-name`} className="text-[13px] font-medium text-fg-secondary">
              Name
            </label>
            <Input
              id={`${ids}-name`}
              placeholder="Defaults to the file or URL"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[13px] font-medium text-fg-secondary">Metadata</span>
              <Button
                variant="link"
                size="28"
                onClick={() => {
                  setMetadata([...metadata, { key: "", value: "" }]);
                }}
              >
                <Plus aria-hidden />
                Add field
              </Button>
            </div>
            {metadata.map((row, index) => (
              <div key={index} className="flex items-center gap-1.5">
                <Input
                  aria-label="Metadata key"
                  mono
                  placeholder="key"
                  className="h-8"
                  value={row.key}
                  onChange={(event) => {
                    setMetadata(
                      metadata.map((item, at) =>
                        at === index ? { ...item, key: event.target.value } : item,
                      ),
                    );
                  }}
                />
                <Input
                  aria-label="Metadata value"
                  mono
                  placeholder="value"
                  className="h-8"
                  value={row.value}
                  onChange={(event) => {
                    setMetadata(
                      metadata.map((item, at) =>
                        at === index ? { ...item, value: event.target.value } : item,
                      ),
                    );
                  }}
                />
                <Button
                  variant="icon"
                  size="28"
                  aria-label="Remove field"
                  onClick={() => {
                    setMetadata(metadata.filter((_, at) => at !== index));
                  }}
                >
                  <X aria-hidden />
                </Button>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-x-2 gap-y-1.5">
            <span className="text-[13px] font-medium text-fg-secondary">Reader</span>
            <span className="text-[13px] font-medium text-fg-secondary">Chunker</span>
            <Select value={reader} onValueChange={setReader}>
              <SelectTrigger aria-label="Reader" className="h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={AUTO}>Auto by file type</SelectItem>
                {readers.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.name ?? item.id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={chunker} onValueChange={setChunker}>
              <SelectTrigger aria-label="Chunker" className="h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={AUTO}>Reader default</SelectItem>
                {chunkers.map(([key, item]) => (
                  <SelectItem key={key} value={item.key}>
                    {item.name ?? item.key}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <label className="flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={skipExisting}
              onChange={(event) => {
                setSkipExisting(event.target.checked);
              }}
            />
            Skip content that already exists
          </label>
        </div>
        <footer className="flex justify-end gap-2 border-t border-border-subtle px-5 py-3">
          <Button variant="outline" size="30" disabled={busy} onClick={reset}>
            Cancel
          </Button>
          <Button variant="primary" size="30" disabled={!ready || busy} onClick={() => void submit()}>
            {busy ? "Adding…" : `Add to ${base.name}`}
          </Button>
        </footer>
      </PermissionGate>
    </aside>
  );
}
