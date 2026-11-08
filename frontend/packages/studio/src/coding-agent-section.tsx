// The coding-agent settings of an agent stored in Studio: the harness, its outputs folder and the sandbox each
// session gets. They live in the agent's metadata (`metadata.agnostic.coding_agent`), the marker that makes the
// runtime run the agent through the harness; every edit writes that nested object, leaving the rest of the
// metadata as it is.
import { CodingAgentBadge, codingMarker, type CodingSandbox } from "@agnostic/core";
import {
  Accordion,
  AccordionSection,
  Callout,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@agnostic/ui";

import { isRecord, type Config } from "./config";
import { CODING_SECTION, useConfigSchema, type CodingField } from "./document";
import { fieldId, type FormContext } from "./form";

export const CODING_MARKER_PATH = ["metadata", "agnostic", "coding_agent"] as const;

/** Whether an agent's config carries the coding-agent marker. */
export function isCodingAgent(config: Config | undefined): boolean {
  return codingMarker(config?.metadata) !== undefined;
}

function setIn(value: unknown, path: readonly string[], next: unknown): unknown {
  const [head, ...rest] = path;
  if (head === undefined) return next;
  const object = isRecord(value) ? { ...value } : {};
  const child = setIn(object[head], rest, next);
  if (child === undefined || (isRecord(child) && rest.length > 0 && Object.keys(child).length === 0)) {
    // eslint-disable-next-line @typescript-eslint/no-dynamic-delete -- marker keys are setting names
    delete object[head];
  } else {
    object[head] = child;
  }
  return object;
}

/**
 * The config with one coding-agent setting changed (`["sandbox", "cpus"]`); `undefined` removes it, so the runtime
 * applies its default. The marker itself stays, even when only its harness is left.
 */
export function withCodingSetting(config: Config, path: readonly string[], value: unknown): Config {
  const marker = codingMarker(config.metadata) ?? {};
  const nextMarker = setIn(marker, path, value);
  const metadata = setIn(
    config.metadata,
    CODING_MARKER_PATH.slice(1),
    isRecord(nextMarker) ? nextMarker : {},
  );
  return { ...config, metadata };
}

function getIn(value: unknown, path: readonly string[]): unknown {
  let current = value;
  for (const key of path) {
    if (!isRecord(current)) return undefined;
    current = current[key];
  }
  return current;
}

function CodingFieldControl({
  field,
  marker,
  ctx,
}: {
  field: CodingField;
  marker: Record<string, unknown>;
  ctx: FormContext;
}) {
  const { info } = field;
  const id = fieldId([...CODING_MARKER_PATH, ...field.path].join("."));
  const value = getIn(marker, field.path);
  const readOnly = ctx.readOnly ?? false;
  const set = (next: unknown) => {
    ctx.onChange((config) => withCodingSetting(config, field.path, next));
  };
  const fallback =
    typeof info.default === "string" || typeof info.default === "number" ? String(info.default) : "";
  let control;
  if (info.widget === "select" && info.options?.length) {
    const current = typeof value === "string" ? value : fallback;
    control = (
      <Select
        value={current}
        disabled={readOnly}
        onValueChange={(next) => {
          set(!field.required && next === info.default ? undefined : next);
        }}
      >
        <SelectTrigger id={id} className="h-8 w-40">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {info.options.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  } else if (field.type === "number" || field.type === "integer" || info.widget === "number") {
    control = (
      <Input
        id={id}
        type="number"
        mono
        className="h-8 w-28"
        readOnly={readOnly}
        step={field.type === "integer" ? 1 : "any"}
        value={typeof value === "number" ? String(value) : ""}
        placeholder={fallback}
        onChange={(event) => {
          const raw = event.target.value;
          set(raw === "" ? undefined : Number(raw));
        }}
      />
    );
  } else {
    control = (
      <Input
        id={id}
        mono
        className="h-8"
        readOnly={readOnly}
        value={typeof value === "string" ? value : ""}
        placeholder={fallback}
        onChange={(event) => {
          set(event.target.value || undefined);
        }}
      />
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-[12.5px] font-medium text-fg-secondary">
        {info.label}
      </label>
      {control}
      {info.help && <p className="text-[11.5px] text-fg-muted">{info.help}</p>}
    </div>
  );
}

function sandboxOf(marker: Record<string, unknown>): CodingSandbox {
  const sandbox = isRecord(marker.sandbox) ? (marker.sandbox as Partial<CodingSandbox>) : {};
  return { ...sandbox, provider: sandbox.provider === "e2b" ? "e2b" : "docker" };
}

/** The coding-agent section of the agent form; renders nothing for an agent without the marker. */
export function CodingAgentSection({ ctx }: { ctx: FormContext }) {
  const schema = useConfigSchema("agent");
  const marker = codingMarker(ctx.config.metadata);
  if (!marker) return null;
  const sandbox = sandboxOf(marker);
  const harness = typeof marker.harness === "string" ? marker.harness : "pi";
  const title = schema.sections.find((section) => section.id === CODING_SECTION)?.label ?? "Coding agent";
  // The E2B template only applies to E2B sandboxes, the image only to Docker ones.
  const shown = schema.coding.filter((field) => {
    const key = field.path.join(".");
    if (key === "sandbox.template") return sandbox.provider === "e2b";
    if (key === "sandbox.image") return sandbox.provider === "docker";
    return true;
  });
  const own = shown.filter((field) => field.path.length === 1);
  const nested = shown.filter((field) => field.path.length > 1);
  return (
    <Accordion aria-label="Coding agent settings">
      <AccordionSection
        id={`section-${CODING_SECTION}`}
        title={title}
        adornment={<CodingAgentBadge harness={harness} sandbox={sandbox} />}
        defaultOpen
        contentClassName="flex flex-col gap-4"
      >
        <Callout tone="info" title="Test runs use the published version">
          The runtime starts a coding agent from its current version, so a draft&apos;s test run still uses
          the published settings. Publish to try changes to the harness or the sandbox.
        </Callout>
        {schema.isPending && <p className="text-[12.5px] text-fg-muted">Loading the settings…</p>}
        {!schema.isPending && shown.length === 0 && (
          <p className="text-[12.5px] text-fg-muted">
            This control plane doesn&apos;t describe the coding-agent settings; edit them in the agent&apos;s
            metadata under Advanced.
          </p>
        )}
        {own.map((field) => (
          <CodingFieldControl key={field.path.join(".")} field={field} marker={marker} ctx={ctx} />
        ))}
        {nested.length > 0 && (
          <fieldset className="flex flex-col gap-4 border-t border-border-subtle pt-3">
            <legend className="pr-2 font-mono text-[11px] tracking-[0.04em] text-fg-muted uppercase">
              Sandbox
            </legend>
            {nested.map((field) => (
              <CodingFieldControl key={field.path.join(".")} field={field} marker={marker} ctx={ctx} />
            ))}
          </fieldset>
        )}
      </AccordionSection>
    </Accordion>
  );
}
