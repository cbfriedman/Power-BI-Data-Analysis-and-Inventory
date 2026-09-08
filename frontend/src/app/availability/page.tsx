import { Placeholder } from "@/components/Placeholder";
import { AvailabilityIcon } from "@/components/icons";

export default function AvailabilityPage() {
  return (
    <Placeholder
      title="Availability"
      icon={AvailabilityIcon}
      summary="Stock transitions detected by comparing each import against the previous one. A watched product coming back into stock appears here first."
      capabilities={[
        "See items that just became available, newest first",
        "Trace an event back to the exact import that revealed it",
        "Acknowledge an event once it has been acted on",
      ]}
    />
  );
}
