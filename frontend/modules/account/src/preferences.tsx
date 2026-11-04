// Display preferences, kept in `me.preferences` (any key; PATCH /me merges them): API hints and density.
import { describeError, meGetMeQueryKey, meUpdateMeMutation, type MeOut } from "@agnostic/api";
import { Callout, RadioCards, Switch, type Density, type RadioCardOption } from "@agnostic/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";

const DENSITY_OPTIONS: readonly RadioCardOption<Density>[] = [
  { value: "comfortable", label: "Comfortable", description: "The default spacing." },
  { value: "compact", label: "Compact", description: "Smaller controls and table rows, more on screen." },
];

export function Preferences({ me }: { me: MeOut }) {
  const queryClient = useQueryClient();
  const update = useMutation({
    ...meUpdateMeMutation(),
    onSuccess: (data) => {
      queryClient.setQueryData(meGetMeQueryKey(), data);
    },
  });
  const apiHints = me.preferences.api_hints === true;
  const density: Density = me.preferences.density === "compact" ? "compact" : "comfortable";
  return (
    <div className="flex max-w-xl flex-col gap-4">
      <Switch
        label="API hints"
        description="Show the API call behind each screen, so you can script what you click."
        checked={apiHints}
        disabled={update.isPending}
        onCheckedChange={(checked) => {
          update.mutate({ body: { preferences: { api_hints: checked } } });
        }}
      />
      <RadioCards
        legend="Density"
        value={density}
        onValueChange={(next) => {
          update.mutate({ body: { preferences: { density: next } } });
        }}
        options={DENSITY_OPTIONS}
      />
      {update.error && <Callout tone="danger">{describeError(update.error).reason}</Callout>}
    </div>
  );
}
