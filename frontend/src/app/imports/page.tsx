import { Placeholder } from "@/components/Placeholder";
import { ImportsIcon } from "@/components/icons";

export default function ImportsPage() {
  return (
    <Placeholder
      title="Imports"
      icon={ImportsIcon}
      summary="Upload a vendor inventory file and follow it through parsing, validation, and matching. The original file is kept exactly as received, before anything reads it."
      capabilities={[
        "Upload a CSV or XLSX file and watch the run progress",
        "Read a validation report tied to real line numbers in the original file",
        "Re-run a failed import without duplicating what already succeeded",
      ]}
    />
  );
}
