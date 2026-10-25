import { useLang } from "../i18n";

// "Adjust for major tournaments": count only Abyss Cup qualifiers and playoffs and the numbered Abyss Fight Club
// events of House of the Hearth (no fast cups or other series).
export function MajorToggle({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  const { t } = useLang();
  return (
    <button type="button" className={`player-major${on ? " active" : ""}`} aria-pressed={on} onClick={() => onChange(!on)}
      title={t("Only Abyss Cup qualifiers and playoffs and House of the Hearth's Abyss Fight Club; fast cups and other series are left out",
               "Только квалификации и плей-офф Abyss Cup и Abyss Fight Club от House of the Hearth; быстрые турниры и другие серии не учитываются")}>
      {on ? t("Major tournaments only", "Только мейджоры") : t("Adjust for major tournaments", "Учитывать только мейджоры")}
    </button>
  );
}
