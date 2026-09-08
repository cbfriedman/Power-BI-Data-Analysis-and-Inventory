import { Placeholder } from "@/components/Placeholder";
import { ProfilesIcon } from "@/components/icons";

export default function ProfilesPage() {
  return (
    <Placeholder
      title="Import profiles"
      icon={ProfilesIcon}
      summary="Each vendor sends a differently shaped file. A profile describes how to read one — its columns, encoding, and how it expresses availability — as configuration rather than code."
      capabilities={[
        "Onboard a new vendor's file format without a code change or deployment",
        "Map that vendor's column names onto the fields the system needs",
        "Keep earlier versions, so past imports stay interpretable",
      ]}
    />
  );
}
