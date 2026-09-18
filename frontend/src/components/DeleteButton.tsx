"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { proxyFetch } from "@/lib/client-fetch";

export function DeleteButton({ path }: { path: string }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  async function handleClick() {
    setLoading(true);
    try {
      await proxyFetch(path, { method: "DELETE" });
      router.refresh();
    } finally {
      setLoading(false);
    }
  }

  return (
    <button
      onClick={handleClick}
      disabled={loading}
      className="text-xs text-red-600 underline hover:text-red-800 disabled:opacity-50"
    >
      {loading ? "Removendo..." : "Remover"}
    </button>
  );
}
