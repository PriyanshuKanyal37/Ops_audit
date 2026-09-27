import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Report from "@/components/Report";
import { getReport } from "@/lib/api";

type Props = { params: Promise<{ id: string }> };

// The permanent report link (PRD §9.3). Reports are private-by-obscurity, so never indexed.
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const report = await getReport(id);
  return {
    title: report ? `${report.display_name}: Ops Clarity Audit` : "Report not found",
    robots: { index: false, follow: false },
  };
}

export default async function ReportPage({ params }: Props) {
  const { id } = await params;
  const report = await getReport(id);
  if (!report) notFound();
  return <Report report={report} />;
}
