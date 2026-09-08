import { Placeholder } from "@/components/Placeholder";
import { ProductsIcon } from "@/components/icons";

export default function ProductsPage() {
  return (
    <Placeholder
      title="Products"
      icon={ProductsIcon}
      summary="The canonical product catalogue synchronised from Nineyard, with every identifier that resolves to a product — catalogue number, UPC, and marketplace SKUs."
      capabilities={[
        "Search the catalogue by name, catalogue number, or UPC",
        "See every identifier attached to a product, and where it came from",
        "Review the marketplace listings mapped to each product",
      ]}
    />
  );
}
