import { Suspense } from "react";
import { ClinicianDirectory } from "./ClinicianDirectory";

export default function ClinicianPage() {
  return (
    <Suspense fallback={null}>
      <ClinicianDirectory />
    </Suspense>
  );
}
