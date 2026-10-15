import { useLang } from "../i18n";

// "Adjust for major tournaments": count only Abyss Cup qualifiers and playoffs (no fast cups or other series).
export function MajorToggle({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  const { t } = useLang();
  return (
    <button type="button" className={`player-major${on ? " active" : ""}`} aria-pressed={on} onClick={() => onChange(!on)}
      title={t("Only Abyss Cup qualifiers and playoffs; fast cups and other series are left out",
               "Только квалификации и плей-офф Abyss Cup; быстрые турниры и другие серии не учитываются")}>
      {on ? t("Major tournaments only", "Только мейджоры") : t("Adjust for major tournaments", "Учитывать только мейджоры")}
    </button>
  );
}
