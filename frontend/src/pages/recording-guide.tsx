import { useNavigate } from "react-router";
import { RecordingGuide } from "@/components/recording-guide/RecordingGuide";

export function RecordingGuidePage() {
  const navigate = useNavigate();

  return (
    <RecordingGuide
      onGoToSetup={() => navigate("/app/session")}
    />
  );
}
