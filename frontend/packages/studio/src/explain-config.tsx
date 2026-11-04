// "Explain this config": a generated plain-words reading of the configuration being edited (unsaved edits
// included). Hidden when AI summaries are off.
import { GeneratedText, useAssistant } from "@agnostic/assistant";
import { Button, Popover, PopoverContent, PopoverTrigger } from "@agnostic/ui";
import { Sparkles } from "lucide-react";

import type { Config } from "./config";

export function ExplainConfig({
  instance,
  componentId,
  config,
}: {
  instance: string;
  componentId: string;
  config: Config | undefined;
}) {
  const { available } = useAssistant("summaries");
  if (!available || !config) return null;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="32">
          <Sparkles aria-hidden />
          Explain
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[480px]" aria-label="Explain this config">
        <GeneratedText
          instance={instance}
          action="Explain this config"
          label="Generated explanation"
          request={{
            kind: "studio.config_explanation",
            subject: { component_id: componentId },
            material: config,
          }}
        />
      </PopoverContent>
    </Popover>
  );
}
