import { Placeholder } from "@/components/Placeholder";
import { AuditIcon } from "@/components/icons";

export default function AuditPage() {
  return (
    <Placeholder
      title="Audit log"
      icon={AuditIcon}
      summary="An append-only record of every important change: who did it, what changed, and when. The database itself rejects any attempt to edit or delete an entry."
      capabilities={[
        "Filter by person, action, record, or date range",
        "See the before and after state of any change",
        "Follow one request across the logs and the audit trail by its id",
      ]}
    />
  );
}
