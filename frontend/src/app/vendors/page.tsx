import { Placeholder } from "@/components/Placeholder";
import { VendorsIcon } from "@/components/icons";

export default function VendorsPage() {
  return (
    <Placeholder
      title="Vendors"
      icon={VendorsIcon}
      summary="Supplier records: contact details, currency, status, and default lead times. Every change is written to the audit trail with the person who made it."
      capabilities={[
        "Add and edit suppliers, and deactivate ones no longer used",
        "Set default lead times used by later replenishment work",
        "See the full change history for any supplier",
      ]}
    />
  );
}
