import { redirect } from "next/navigation";

// This app only serves the audit.
export default function Home() {
  redirect("/audit");
}
