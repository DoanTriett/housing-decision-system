import { LiveRequestView } from "@/components/live-request-view";

type RequestLivePageProps = {
  params: { id: string };
};

export default function RequestLivePage({ params }: RequestLivePageProps) {
  return <LiveRequestView requestId={params.id} />;
}
