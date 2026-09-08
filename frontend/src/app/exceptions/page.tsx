import { Placeholder } from "@/components/Placeholder";
import { ExceptionsIcon } from "@/components/icons";

export default function ExceptionsPage() {
  return (
    <Placeholder
      title="Exception queue"
      icon={ExceptionsIcon}
      summary="Rows the matcher could not resolve on its own. Nothing here was guessed: the system found no match, found more than one, or could only suggest — so it asked instead."
      capabilities={[
        "Review a row beside the candidate products and why each was suggested",
        "Approve a mapping once and have it applied automatically thereafter",
        "See the full rule-by-rule trail behind every decision",
      ]}
    />
  );
}
