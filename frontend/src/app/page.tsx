import Link from "next/link";

import { SystemStatusCard } from "@/components/ApiStatus";
import {
  ExceptionsIcon,
  ImportsIcon,
  MatchIcon,
  ProductsIcon,
  VendorsIcon,
  WatchlistIcon,
} from "@/components/icons";

/**
 * The dashboard.
 *
 * Deliberately shows no counts or charts. Every number here would be zero or
 * invented, and an invented figure on the first screen a client sees is the
 * fastest way to lose their trust in every other number the system reports.
 *
 * What it shows instead is true and useful: live system health, and how the
 * system actually processes a vendor file.
 */

const PIPELINE = [
  {
    title: "Receive",
    text: "A vendor's CSV or XLSX is uploaded and kept byte-for-byte, before anything parses it.",
  },
  {
    title: "Parse",
    text: "A per-vendor profile maps that vendor's columns. Every value is read as text, so leading zeros survive.",
  },
  {
    title: "Match",
    text: "UPC, then catalogue number, then approved mappings. First unambiguous rule wins, and it is recorded.",
  },
  {
    title: "Review",
    text: "Anything uncertain goes to a person. Nothing is guessed, and approvals are reused thereafter.",
  },
  {
    title: "Detect",
    text: "New stock levels are compared against the last snapshot, raising an alert when a watched item returns.",
  },
];

const SECTIONS = [
  {
    href: "/products",
    label: "Products",
    icon: ProductsIcon,
    text: "The canonical catalogue, with every identifier that resolves to a product.",
  },
  {
    href: "/vendors",
    label: "Vendors",
    icon: VendorsIcon,
    text: "Suppliers, their contact details, and their default lead times.",
  },
  {
    href: "/imports",
    label: "Imports",
    icon: ImportsIcon,
    text: "Upload a vendor file, follow the run, and read its validation report.",
  },
  {
    href: "/exceptions",
    label: "Exception queue",
    icon: ExceptionsIcon,
    text: "Rows the matcher could not resolve on its own, waiting for a decision.",
  },
  {
    href: "/watchlist",
    label: "Watchlist",
    icon: WatchlistIcon,
    text: "Products you want to buy, watched for the moment a vendor has them again.",
  },
  {
    href: "/availability",
    label: "Availability",
    icon: MatchIcon,
    text: "Stock transitions detected between one import and the next.",
  },
];

export default function DashboardPage() {
  return (
    <>
      <header className="page-header">
        <div className="page-header__title-row">
          <h1>Purchasing &amp; Replenishment</h1>
        </div>
        <p className="page-header__lede">
          One catalogue, every vendor&rsquo;s inventory, and a matching process that asks
          rather than guesses — so the numbers behind a purchasing decision can be trusted.
        </p>
      </header>

      <div className="grid grid--2" style={{ marginBottom: 26 }}>
        <SystemStatusCard />

        <div className="card">
          <div className="card__header">
            <span className="card__title">
              <MatchIcon />
              Matching policy
            </span>
          </div>
          <div className="kv">
            <div className="kv__row">
              <span className="kv__key">1 &nbsp;Normalised UPC</span>
              <span className="kv__value">Automatic</span>
            </div>
            <div className="kv__row">
              <span className="kv__key">2 &nbsp;Catalogue item number</span>
              <span className="kv__value">Automatic</span>
            </div>
            <div className="kv__row">
              <span className="kv__key">3 &nbsp;Approved vendor SKU</span>
              <span className="kv__value">Automatic</span>
            </div>
            <div className="kv__row">
              <span className="kv__key">4 &nbsp;Approved marketplace SKU</span>
              <span className="kv__value">Automatic</span>
            </div>
            <div className="kv__row">
              <span className="kv__key">5 &nbsp;Suggested match</span>
              <span className="kv__value" style={{ color: "var(--warn)" }}>
                Needs approval
              </span>
            </div>
          </div>
          <p className="card__note">
            A description alone never matches a product automatically. Anything ambiguous
            goes to the exception queue rather than being resolved by guesswork.
          </p>
        </div>
      </div>

      <section style={{ marginBottom: 26 }}>
        <div className="card">
          <div className="card__header">
            <span className="card__title">
              <ImportsIcon />
              How a vendor file becomes trusted data
            </span>
          </div>
          <ol className="pipeline" style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {PIPELINE.map((step, index) => (
              <li className="pipeline__step" key={step.title}>
                <div className="pipeline__num">{index + 1}</div>
                <div className="pipeline__title">{step.title}</div>
                <div className="pipeline__text">{step.text}</div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section>
        <h2 style={{ marginBottom: 12 }}>Sections</h2>
        <div className="grid grid--3">
          {SECTIONS.map((section) => {
            const IconComponent = section.icon;
            return (
              <Link href={section.href} key={section.href} className="card-link">
                <span className="card-link__head">
                  <span className="card-link__icon">
                    <IconComponent />
                  </span>
                  <span className="card-link__title">{section.label}</span>
                </span>
                <span className="card-link__text">{section.text}</span>
              </Link>
            );
          })}
        </div>
      </section>
    </>
  );
}
