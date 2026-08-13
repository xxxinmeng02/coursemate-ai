"use client";

import { useEffect, useState } from "react";

type BackendState = "Checking" | "Connected" | "Disconnected";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function BackendStatus() {
  const [status, setStatus] = useState<BackendState>("Checking");

  useEffect(() => {
    const controller = new AbortController();

    async function checkBackend() {
      try {
        const response = await fetch(`${API_URL}/health`, {
          cache: "no-store",
          signal: controller.signal,
        });
        const data: { status?: string } = await response.json();

        setStatus(response.ok && data.status === "ok" ? "Connected" : "Disconnected");
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setStatus("Disconnected");
        }
      }
    }

    void checkBackend();

    return () => controller.abort();
  }, []);

  const statusColor =
    status === "Connected"
      ? "text-green-700"
      : status === "Disconnected"
        ? "text-red-700"
        : "text-amber-700";

  return (
    <p aria-live="polite">
      Backend: <span className={`font-medium ${statusColor}`}>{status}</span>
    </p>
  );
}
