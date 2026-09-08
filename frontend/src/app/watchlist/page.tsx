import { Placeholder } from "@/components/Placeholder";
import { WatchlistIcon } from "@/components/icons";

export default function WatchlistPage() {
  return (
    <Placeholder
      title="Watchlist"
      icon={WatchlistIcon}
      summary="Products you intend to buy, watched for the moment a vendor has them in stock again. A buying list, not a report of everything that happens to be at zero."
      capabilities={[
        "Add a product to watch, with the quantity and maximum cost you want",
        "Watch every vendor, or one particular vendor",
        "See how long an item has been unavailable",
      ]}
    />
  );
}
