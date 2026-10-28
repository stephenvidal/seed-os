import { Compass } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState } from "../components/ui/EmptyState";
import { Panel } from "../components/ui/Panel";

export function NotFoundPage() {
  return (
    <Panel>
      <EmptyState icon={Compass} title="This page does not exist">
        <Link to="/" className="text-accent underline-offset-2 hover:underline">
          Return to Command Center
        </Link>
      </EmptyState>
    </Panel>
  );
}
