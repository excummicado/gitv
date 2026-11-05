import { useLang } from "../i18n";
import { CoffeeIcon } from "./CoffeeIcon";
import "./player-nick.css";

// Players who donated to the site, by their player id: their nickname shimmers in rainbow colours everywhere it's shown,
// with the Ko-fi cup after it.
const DONORS = new Set(["689240ed98475bdb81442fef"]); // phanora

// A player's nickname. id: null for someone without a player page.
export function Nick({ id, name }: { id: string | null | undefined; name: string }) {
  const { t } = useLang();
  if (!id || !DONORS.has(id)) return <>{name}</>;
  return (
    // One element: some of the places a nickname goes lay their children out in a column
    <span className="gitv-donor-nick">
      <span className="gitv-donor">{name}</span>
      <span className="gitv-donor-cup" role="img" aria-label={t("This player donated to GITV", "Этот игрок сделал пожертвование на GITV")}><CoffeeIcon /></span>
    </span>
  );
}
