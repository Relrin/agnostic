import type { Meta, StoryObj } from "@storybook/react-vite";

import {
  accents,
  allColors,
  avatarPalette,
  contrastPairs,
  contrastRatio,
  entities,
  lines,
  surfaces,
  text,
} from "../lib/tokens";

function Swatches({ title, values }: { title: string; values: Record<string, string> }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-[15px] font-semibold">{title}</h2>
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-2">
        {Object.entries(values).map(([name, hex]) => (
          <li
            key={name}
            className="flex items-center gap-2.5 rounded-tile border border-border bg-surface p-2"
          >
            <span
              aria-hidden
              className="size-8 shrink-0 rounded-control border border-border-strong"
              style={{ background: `var(${name})` }}
            />
            <span className="flex min-w-0 flex-col">
              <code className="truncate font-mono text-[12px] text-fg">{name}</code>
              <span className="font-mono text-[11px] text-fg-muted">{hex}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function TokensPage() {
  return (
    <div className="flex max-w-5xl flex-col gap-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-[22px] font-semibold">Tokens</h1>
        <p className="text-[13.5px] text-fg-secondary">
          Values from the prototype (04-design-system §2). Components use these semantic tokens only.
        </p>
      </header>
      <Swatches title="Surfaces" values={surfaces} />
      <Swatches title="Lines" values={lines} />
      <Swatches title="Text" values={text} />
      <Swatches title="Accents" values={accents} />
      <Swatches title="Entities, registry and charts" values={entities} />
      <section className="flex flex-col gap-2">
        <h2 className="text-[15px] font-semibold">Avatars</h2>
        <div className="flex gap-2">
          {avatarPalette.map(([bg, fg]) => (
            <span
              key={bg}
              className="grid size-8 place-items-center rounded-full text-[12px] font-semibold"
              style={{ background: bg, color: fg }}
            >
              DO
            </span>
          ))}
        </div>
      </section>
      <section className="flex flex-col gap-2">
        <h2 className="text-[15px] font-semibold">Contrast</h2>
        <table className="w-full max-w-xl text-left text-[13px]">
          <thead className="font-mono text-[11px] text-fg-muted uppercase">
            <tr>
              <th className="py-1">Text</th>
              <th>Background</th>
              <th>Ratio</th>
              <th>Needs</th>
            </tr>
          </thead>
          <tbody>
            {contrastPairs.map(({ fg, bg, min }) => {
              const ratio = contrastRatio(allColors[fg] ?? "#000000", allColors[bg] ?? "#000000");
              return (
                <tr key={`${fg}-${bg}`} className="border-t border-divider-row">
                  <td className="py-1.5 font-mono" style={{ color: `var(${fg})`, background: `var(${bg})` }}>
                    {fg}
                  </td>
                  <td className="font-mono">{bg}</td>
                  <td className="tabular">{ratio.toFixed(2)}:1</td>
                  <td className="tabular">{min}:1</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}

const meta = { title: "Foundations/Tokens", component: TokensPage } satisfies Meta<typeof TokensPage>;
export default meta;

export const Tokens: StoryObj<typeof meta> = {};
