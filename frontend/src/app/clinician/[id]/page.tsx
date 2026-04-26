import { Suspense } from "react";
import { ClinicianView } from "../ClinicianView";

export default async function ClinicianDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <Suspense fallback={null}>
      <ClinicianView id={id} />
    </Suspense>
  );
}
