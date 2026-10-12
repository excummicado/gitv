import type { Route } from "./+types/home";
import { Welcome } from "../home/welcome";

export function meta({ }: Route.MetaArgs) {
  return [
    { title: "GITV · Layout & Font Comparison" },
    { name: "description", content: "A static GITV sports portal layout and serif font comparison." },
  ];
}

export default function Home() {
  return <Welcome />;
}
