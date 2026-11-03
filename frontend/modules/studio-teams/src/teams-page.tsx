import { studioListComponentsOptions } from "@agnostic/api";
import { withQueryFn } from "@agnostic/core";
import {
  ComponentIndex,
  ConfigForm,
  FieldControl,
  MODE_BLURB,
  MODE_LABEL,
  StudioEditor,
  TEAM_MODES,
  flowSteps,
  memberId,
  members,
  modelId,
  teamMode,
  useComponent,
  useConfigSchema,
  withField,
  type DraftDocument,
  type FormContext,
  type MemberEntry,
  type TeamMode,
} from "@agnostic/studio";
import {
  Button,
  Combobox,
  EntitySquare,
  LineLinkBadge,
  LoadingRows,
  RadioCards,
  SortableList,
  cn,
} from "@agnostic/ui";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { Play, Plus, X } from "lucide-react";
import { useState } from "react";

/** `/i/:instance/studio/teams`: teams stored in Studio and defined in code. */
export function TeamsPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  return <ComponentIndex instance={params.instance ?? ""} kind="team" />;
}

const USED = "rgba(125,166,255,0.3)";

/** A 60px sketch of the mode: leader box, member circles (unused ones dashed), or the tasks checklist. */
function ModeDiagram({ mode }: { mode: TeamMode }) {
  const used =
    mode === "route"
      ? [true, false, false]
      : mode === "coordinate"
        ? [true, true, false]
        : [true, true, true];
  return (
    <svg viewBox="0 0 120 60" className="h-[60px] w-full" aria-hidden>
      <rect x="44" y="4" width="32" height="16" rx="4" fill="rgba(183,156,255,0.22)" stroke="#B79CFF" />
      {mode === "tasks"
        ? [0, 1, 2, 3].map((row) => (
            <g key={row}>
              <rect
                x="34"
                y={26 + row * 8}
                width="6"
                height="6"
                rx="1.5"
                fill={row < 2 ? "var(--accent)" : "none"}
                stroke={row < 2 ? "var(--accent)" : "var(--border-dashed)"}
              />
              <line
                x1="44"
                y1={29 + row * 8}
                x2="86"
                y2={29 + row * 8}
                stroke="var(--border-strong)"
                strokeWidth="2"
              />
            </g>
          ))
        : [24, 60, 96].map((x, index) => (
            <g key={x}>
              <line
                x1="60"
                y1="20"
                x2={x}
                y2="42"
                stroke={used[index] ? "var(--fg-muted)" : "var(--border-strong)"}
              />
              <circle
                cx={x}
                cy="48"
                r="8"
                fill={used[index] ? USED : "none"}
                stroke={used[index] ? "var(--modified)" : "var(--border-dashed)"}
                strokeDasharray={used[index] ? undefined : "3 2"}
              />
            </g>
          ))}
    </svg>
  );
}

function TeamWorks({
  ctx,
  fields,
}: {
  ctx: FormContext;
  fields: ReturnType<typeof useConfigSchema>["fields"];
}) {
  const mode = teamMode(ctx.config);
  const span = ctx.spans.mode;
  const settings = mode === "tasks" ? "max_iterations" : "determine_input_for_members";
  const info = fields[settings];
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <p className="flex-1 text-[12px] text-fg-muted">
          <code className="font-mono">mode</code> replaces the legacy respond_directly and
          delegate_to_all_members flags.
        </p>
        {span && (
          <LineLinkBadge
            line={span.line}
            active={ctx.focusedPath === "mode"}
            onClick={() => {
              ctx.onFocusPath(ctx.focusedPath === "mode" ? undefined : "mode");
            }}
          />
        )}
      </div>
      <RadioCards
        legend="Mode"
        value={mode}
        onValueChange={(next) => {
          ctx.onChange((config) => {
            let updated = withField(config, "mode", next);
            updated = withField(updated, "respond_directly", undefined);
            return withField(updated, "delegate_to_all_members", undefined);
          });
        }}
        options={TEAM_MODES.map((value) => ({
          value,
          label: (
            <span className="flex w-full flex-col gap-1">
              <ModeDiagram mode={value} />
              <span className="flex items-center gap-1.5">
                {MODE_LABEL[value]}
                {value === "coordinate" && (
                  <span className="font-mono text-[10.5px] text-fg-muted">default</span>
                )}
              </span>
            </span>
          ),
          description: MODE_BLURB[value],
        }))}
      />
      <div className="flex flex-wrap gap-4 rounded-card border border-border bg-surface p-4">
        <div className="flex min-w-[220px] flex-[2_1_260px] flex-col gap-2">
          <h3 className="text-[13px] font-medium">
            How a request flows in <strong>{MODE_LABEL[mode]}</strong> mode
          </h3>
          <ol className="flex flex-col gap-2" aria-label="Request flow">
            {flowSteps(ctx.config).map((step, index) => (
              <li key={step} className="flex gap-2 text-[12.5px] text-fg-secondary">
                <span className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-surface-hover font-mono text-[11px]">
                  {index + 1}
                </span>
                {step}
              </li>
            ))}
          </ol>
        </div>
        <div className="flex min-w-[180px] flex-[1_1_200px] flex-col gap-2 border-l border-border-subtle pl-4">
          <h3 className="text-[12.5px] font-medium text-fg-secondary">Mode settings</h3>
          {info && <FieldControl name={settings} info={info} ctx={ctx} />}
        </div>
      </div>
    </div>
  );
}

function MemberRow({
  instance,
  member,
  pinned,
  isCode,
  onPin,
  onRemove,
  handle,
  readOnly,
}: {
  instance: string;
  member: MemberEntry;
  pinned: number | undefined;
  isCode: boolean;
  onPin: (version: number) => void;
  onRemove: () => void;
  handle: React.ReactNode;
  readOnly: boolean;
}) {
  const id = memberId(member);
  const detail = useComponent(instance, isCode ? "" : id);
  const stored = isCode ? undefined : detail.data;
  const config = stored?.current?.config ?? stored?.draft?.config ?? undefined;
  const current = stored?.component.current_version ?? undefined;
  const role = typeof config?.role === "string" ? config.role : (stored?.component.description ?? undefined);
  return (
    <div className="flex items-center gap-2 rounded-[10px] border border-border bg-surface px-2 py-2">
      {handle}
      <EntitySquare kind={member.type === "team" ? "team" : "agent"} />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="font-mono text-[12.5px]">
          {id}
          <span className="ml-1.5 text-fg-muted">
            {isCode ? "code" : pinned ? `v${String(pinned)}` : current ? `v${String(current)}` : ""}
          </span>
        </span>
        <span className="truncate text-[12px] text-fg-secondary">
          {role ?? (isCode ? "Defined in code" : "")}
        </span>
        {modelId(config?.model) && (
          <span className="text-[12px] text-fg-muted">{modelId(config?.model)}</span>
        )}
      </div>
      {!readOnly && pinned !== undefined && current !== undefined && pinned < current && (
        <Button
          variant="ghost"
          size="28"
          onClick={() => {
            onPin(current);
          }}
        >
          {`Update to v${String(current)}`}
        </Button>
      )}
      {!readOnly && (
        <Button variant="icon" size="28" aria-label={`Remove ${id}`} onClick={onRemove}>
          <X aria-hidden />
        </Button>
      )}
    </div>
  );
}

function Members({
  instance,
  ctx,
  doc,
  selfId,
}: {
  instance: string;
  ctx: FormContext;
  doc: DraftDocument;
  selfId: string;
}) {
  const list = members(ctx.config);
  const [adding, setAdding] = useState(false);
  const agents = useQuery(
    withQueryFn(studioListComponentsOptions({ path: { instance }, query: { kind: "agent" } })),
  );
  const teams = useQuery(
    withQueryFn(studioListComponentsOptions({ path: { instance }, query: { kind: "team" } })),
  );
  const present = new Set(list.map(memberId));
  const candidates = [
    ...(agents.data ?? []).map((row) => ({
      id: row.component.id,
      type: "agent" as const,
      source: row.component.source,
    })),
    ...(teams.data ?? []).map((row) => ({
      id: row.component.id,
      type: "team" as const,
      source: row.component.source,
    })),
  ].filter((item) => item.id !== selfId && !present.has(item.id));
  const codeIds = new Set(
    [...(agents.data ?? []), ...(teams.data ?? [])]
      .filter((row) => row.component.source === "code")
      .map((row) => row.component.id),
  );
  const readOnly = ctx.readOnly ?? false;
  const update = (next: MemberEntry[]) => {
    ctx.onChange((config) => withField(config, "members", next.length ? next : undefined));
  };
  return (
    <div className="flex flex-col gap-2">
      <SortableList
        aria-label="Members"
        items={list}
        getId={memberId}
        getLabel={memberId}
        disabled={readOnly}
        onReorder={update}
        renderItem={(member, state) => (
          <div
            className={cn(
              ctx.focusedPath === `members[${String(state.index)}]` &&
                "rounded-[10px] ring-[3px] ring-accent/14",
            )}
          >
            <MemberRow
              instance={instance}
              member={member}
              pinned={doc.pins[memberId(member)]}
              isCode={codeIds.has(memberId(member))}
              handle={state.handle}
              readOnly={readOnly}
              onPin={(version) => {
                doc.setPin(memberId(member), version);
              }}
              onRemove={() => {
                doc.setPin(memberId(member), undefined);
                update(list.filter((item) => memberId(item) !== memberId(member)));
              }}
            />
          </div>
        )}
      />
      {!readOnly &&
        (adding ? (
          <Combobox
            aria-label="Add a member"
            mono
            value={undefined}
            placeholder="Pick an agent or team"
            searchPlaceholder="Search agents and teams…"
            emptyText="Every agent and team is a member already."
            options={candidates.map((item) => ({
              value: `${item.type}:${item.id}`,
              label: item.id,
              hint: `${item.type}${item.source === "code" ? " · code" : ""}`,
            }))}
            onValueChange={(value) => {
              setAdding(false);
              const [type, id] = value.split(":", 2) as ["agent" | "team", string];
              update([...list, type === "team" ? { type, team_id: id } : { type, agent_id: id }]);
            }}
          />
        ) : (
          <Button
            variant="dashed-add"
            size="28"
            className="self-start"
            onClick={() => {
              setAdding(true);
            }}
          >
            <Plus aria-hidden />
            Add from Registry
          </Button>
        ))}
    </div>
  );
}

/** `/i/:instance/studio/teams/:id`: the team editor. */
export function TeamEditorPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const instance = params.instance ?? "";
  const componentId = params.componentId ?? "";
  const schema = useConfigSchema("team");
  return (
    <StudioEditor
      instance={instance}
      componentId={componentId}
      kind="team"
      toolbarExtra={(doc) => (
        <Button asChild variant="ghost" size="30">
          <Link
            to={`/i/${encodeURIComponent(instance)}/chat/teams/${encodeURIComponent(componentId)}`}
            search={doc.draft ? { version: doc.draft.version } : {}}
          >
            <Play aria-hidden />
            Test in Chat
          </Link>
        </Button>
      )}
      renderForm={(ctx, doc) =>
        schema.isPending ? (
          <LoadingRows rows={6} label="Loading the form" />
        ) : (
          <ConfigForm
            sections={schema.sections}
            fields={schema.fields}
            ctx={ctx}
            ariaLabel="Team configuration"
            custom={{
              team: <TeamWorks ctx={ctx} fields={schema.fields} />,
              members: <Members instance={instance} ctx={ctx} doc={doc} selfId={componentId} />,
            }}
          />
        )
      }
    />
  );
}
