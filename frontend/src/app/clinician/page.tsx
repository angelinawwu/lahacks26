import { Suspense } from "react";
import { ClinicianView } from "./ClinicianView";

export default function ClinicianPage() {
  return (
    <Suspense fallback={null}>
      <ClinicianView />
    </Suspense>
  );
}
