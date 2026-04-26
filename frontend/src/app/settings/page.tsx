import { Suspense } from "react";
import { SettingsView } from "./SettingsView";

export default function SettingsPage() {
  return (
    <Suspense fallback={null}>
      <SettingsView />
    </Suspense>
  );
}
