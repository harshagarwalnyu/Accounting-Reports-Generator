import { useEffect, useState } from "react";
import { API_BASE_URL } from "../api";

export type ProgressEvent = {
  step: string;
  progress: number;
  message?: string;
  pdf_url?: string;
};

export function useSSE(jobId: string | null) {
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;

    const eventSource = new EventSource(`${API_BASE_URL}/reports/${jobId}/stream`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setEvents((prev) => [...prev, data]);
        
        if (data.step === "done") {
          setIsComplete(true);
          eventSource.close();
        } else if (data.step === "error") {
          setError(data.message || "An error occurred");
          eventSource.close();
        }
      } catch (err) {
        console.error("Failed to parse SSE message", err);
      }
    };

    eventSource.onerror = (err) => {
      // If we already completed cleanly, ignore the close event
      if (eventSource.readyState === EventSource.CLOSED) return;
      
      console.error("EventSource error", err);
      setError("Connection to server lost.");
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [jobId]);

  return { events, isComplete, error };
}
