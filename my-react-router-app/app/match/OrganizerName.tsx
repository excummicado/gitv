import { Link } from "react-router";
import type { Organizer } from "./api";

// A tournament organizer; links to their player page when they also played.
export function OrganizerName({ organizer }: { organizer: Organizer }) {
  return organizer.played
    ? <Link className="match-organizer-link" to={`/player/${organizer.id}`}>{organizer.name}</Link>
    : <>{organizer.name}</>;
}
